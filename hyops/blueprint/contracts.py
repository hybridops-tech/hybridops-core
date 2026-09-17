"""Blueprint step contract and inputs materialization helpers."""

from __future__ import annotations

import getpass
import os
import re
from pathlib import Path
from typing import Any

import yaml

from hyops.authority import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityReceipt,
    AuthorityRequirement,
    AuthorityResolver,
    default_authority_registry,
)
from hyops.authority.compat import legacy_authority_contract
from hyops.commands._apply_helpers import sanitize_rerun_inputs
from hyops.runtime.module_state import read_module_state

from .common import as_mapping, merge_mappings


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        token = str(item or "").strip()
        if token:
            out.append(token)
    return out


def module_state_status(state_root: Path, module_ref: str) -> str:
    try:
        payload = read_module_state(state_root, module_ref)
    except Exception:
        return ""
    return str(payload.get("status") or "").strip().lower()


def module_state_ok(state_root: Path, module_ref: str) -> bool:
    return module_state_status(state_root, module_ref) == "ok"


def step_state_ref(step: dict[str, Any]) -> str:
    module_ref = str(step.get("module_ref") or "").strip()
    state_instance = str(step.get("state_instance") or "").strip().lower()
    if state_instance:
        return f"{module_ref}#{state_instance}"
    return module_ref


def load_inputs_file(path: Path, field: str) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return as_mapping(payload, field)


def _load_skip_baseline_inputs(state_root: Path, module_ref: str) -> dict[str, Any]:
    try:
        state = read_module_state(state_root, module_ref)
    except Exception:
        return {}

    candidates: list[Path] = []
    for key in ("resolved_inputs_file", "rerun_inputs_file"):
        raw = str(state.get(key) or "").strip()
        if not raw:
            continue
        try:
            candidates.append(Path(raw).expanduser().resolve())
        except Exception:
            continue

    evidence_dir = str(state.get("evidence_dir") or "").strip()
    if evidence_dir:
        try:
            candidates.append((Path(evidence_dir).expanduser().resolve() / "resolved.inputs.yml").resolve())
        except Exception:
            pass

    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(payload, dict):
            return sanitize_rerun_inputs(payload)

    return {}


def _explicit_input_drift_detail(current: Any, baseline: Any, *, path: str) -> str:
    if isinstance(current, dict):
        if not isinstance(baseline, dict):
            return f"{path} changed"
        for key, value in current.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key not in baseline:
                return f"{child_path} changed"
            detail = _explicit_input_drift_detail(value, baseline.get(key), path=child_path)
            if detail:
                return detail
        return ""

    if isinstance(current, list):
        if not isinstance(baseline, list) or current != baseline:
            return f"{path} changed"
        return ""

    if current != baseline:
        return f"{path} changed"
    return ""


def _prune_empty_explicit_inputs(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, raw_value in value.items():
            pruned = _prune_empty_explicit_inputs(raw_value)
            if pruned is None:
                continue
            if isinstance(pruned, str) and not pruned.strip():
                continue
            if isinstance(pruned, (dict, list)) and not pruned:
                continue
            out[str(key)] = pruned
        return out

    if isinstance(value, list):
        out_list = []
        for item in value:
            pruned = _prune_empty_explicit_inputs(item)
            if pruned is None:
                continue
            if isinstance(pruned, str) and not pruned.strip():
                continue
            if isinstance(pruned, (dict, list)) and not pruned:
                continue
            out_list.append(pruned)
        return out_list

    return value


def _resolve_controller_input_tokens(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _resolve_controller_input_tokens(raw_value)
            for key, raw_value in value.items()
        }
    if isinstance(value, list):
        return [_resolve_controller_input_tokens(item) for item in value]
    if isinstance(value, str) and "${USER}" in value:
        username = str(os.environ.get("USER") or getpass.getuser()).strip()
        if not username:
            raise ValueError("unable to resolve ${USER} in blueprint inputs")
        return value.replace("${USER}", username)
    return value


def resolved_step_inputs_file(step: dict[str, Any], payload: dict[str, Any], paths) -> Path | None:
    inline_inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else None
    inputs_file_ref = str(step.get("inputs_file") or "").strip()

    file_inputs: dict[str, Any] = {}
    resolved_file: Path | None = None
    if inputs_file_ref:
        candidate = Path(inputs_file_ref).expanduser()
        if not candidate.is_absolute():
            candidate = (Path(payload["path"]).resolve().parent / candidate).resolve()
        if not candidate.exists():
            raise FileNotFoundError(
                f"step '{step['id']}' inputs_file not found: {candidate}"
            )
        file_inputs = load_inputs_file(candidate, f"steps.{step['id']}.inputs_file")
        resolved_file = candidate

    if inline_inputs is None:
        return resolved_file

    merged = _resolve_controller_input_tokens(
        merge_mappings(file_inputs, inline_inputs)
    )
    bp_token = re.sub(r"[^A-Za-z0-9_.-]+", "_", payload["blueprint_ref"])
    out_dir = paths.work_dir / "blueprint-inputs" / bp_token
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (out_dir / f"{step['id']}.inputs.yml").resolve()
    out_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    os.chmod(out_path, 0o600)
    return out_path


def explicit_step_inputs_changed(step: dict[str, Any], payload: dict[str, Any], paths) -> tuple[bool, str]:
    inputs_file = resolved_step_inputs_file(step, payload, paths)
    if inputs_file is None or not inputs_file.is_file():
        return False, ""

    current_inputs = _prune_empty_explicit_inputs(
        sanitize_rerun_inputs(
        load_inputs_file(inputs_file, f"steps.{step['id']}.resolved_inputs")
        )
    )
    if not current_inputs:
        return False, ""

    baseline_inputs = _load_skip_baseline_inputs(paths.state_dir, step_state_ref(step))
    if not baseline_inputs:
        return False, ""

    detail = _explicit_input_drift_detail(current_inputs, baseline_inputs, path="")
    if not detail:
        return False, ""

    return True, detail


def enforce_step_contracts(
    step: dict[str, Any],
    payload: dict[str, Any],
    paths,
    *,
    assumed_state_ok: set[str] | None = None,
) -> AuthorityReceipt | None:
    contracts = _as_dict(step.get("contracts"))
    policy = _as_dict(payload.get("policy"))
    assumed = set(assumed_state_ok or set())

    def state_ok(module_ref: str) -> bool:
        return module_ref in assumed or module_state_ok(paths.state_dir, module_ref)

    def state_status(module_ref: str) -> str:
        if module_ref in assumed:
            return "planned-ok"
        return module_state_status(paths.state_dir, module_ref) or "missing"

    requires_module_state_ok = _as_str_list(contracts.get("requires_module_state_ok"))
    for module_ref in requires_module_state_ok:
        if not state_ok(module_ref):
            status = state_status(module_ref)
            raise ValueError(
                f"contract failed: required module state is not ok "
                f"({module_ref}, status={status})"
            )

    addressing_mode = str(contracts.get("addressing_mode") or "static").strip().lower()
    raw_requirement = contracts.get("requires_authority")
    legacy = legacy_authority_contract(raw_requirement, policy)
    declarations: dict[str, AuthorityDeclaration] = {}
    for logical_ref, raw in _as_dict(payload.get("authorities")).items():
        declaration = _as_dict(raw)
        declarations[str(logical_ref)] = AuthorityDeclaration(
            logical_ref=str(logical_ref),
            capability=str(declaration.get("capability") or ""),
            provider=str(declaration.get("provider") or ""),
            config=_as_dict(declaration.get("config")),
        )

    requirement: AuthorityRequirement | None = None
    if legacy is not None:
        requirement, declaration = legacy
        declarations[declaration.logical_ref] = declaration
    elif isinstance(raw_requirement, dict):
        requirement = AuthorityRequirement(
            logical_ref=str(raw_requirement.get("ref") or "").strip().lower(),
            capability=str(raw_requirement.get("capability") or "").strip().lower(),
        )
    else:
        logical_ref = str(raw_requirement or "none").strip().lower()
        if logical_ref not in {"", "none"}:
            declaration = declarations.get(logical_ref)
            capability = declaration.capability if declaration else "inventory_ipam"
            requirement = AuthorityRequirement(
                logical_ref=logical_ref,
                capability=capability,
            )

    if addressing_mode == "ipam" and requirement is None:
        raise ValueError(
            "contract failed: addressing_mode=ipam requires an inventory_ipam authority"
        )
    if addressing_mode == "ipam" and requirement.capability != "inventory_ipam":
        raise ValueError(
            "contract failed: addressing_mode=ipam requires authority capability inventory_ipam"
        )
    if requirement is None:
        return None

    context = AuthorityContext(
        runtime_root=Path(paths.root),
        state_root=Path(paths.state_dir),
        env={str(key): str(value) for key, value in os.environ.items()},
        assumed_state_ok=frozenset(assumed),
    )
    resolver = AuthorityResolver(default_authority_registry())
    return resolver.enforce(requirement, declarations, context)
