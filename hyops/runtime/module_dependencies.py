"""Module dependency and execution metadata helpers.

purpose: Resolve dependency imports, required credentials, outputs, and execution hooks.
Architecture Decision: ADR-N/A (module resolution)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from hyops.runtime.coerce import as_bool
from hyops.runtime.module_inputs import parse_input_path, set_nested, try_get_nested
from hyops.runtime.module_state import module_state_path, read_module_state
from hyops.runtime.refs import (
    infer_credential_requirements,
    infer_credential_requirements_from_pack_ref,
    normalize_module_ref,
)


_CRED_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
_OUTPUT_KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def normalize_credential_name(value: str) -> str:
    token = (value or "").strip().lower()
    if not token or not _CRED_RE.fullmatch(token):
        raise ValueError(f"invalid credential provider token: {value!r}")
    return token


def unique(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        k = (item or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def resolve_required_credentials(spec: dict[str, Any], module_ref: str, pack_id: str) -> list[str]:
    inferred = unique(
        [
            *infer_credential_requirements(module_ref),
            *infer_credential_requirements_from_pack_ref(pack_id),
        ]
    )

    requirements = spec.get("requirements")
    if not isinstance(requirements, dict):
        raise ValueError("spec.requirements must be a mapping")

    raw_explicit = requirements.get("credentials")
    if not isinstance(raw_explicit, list):
        raise ValueError("spec.requirements.credentials must be a list")

    explicit: list[str] = []
    for item in raw_explicit:
        if not isinstance(item, str):
            raise ValueError("spec.requirements.credentials entries must be strings")
        explicit.append(normalize_credential_name(item))

    explicit_unique = unique(explicit)
    missing = [provider for provider in inferred if provider not in explicit_unique]
    if missing:
        raise ValueError(
            "spec.requirements.credentials missing inferred provider(s): "
            + ", ".join(sorted(missing))
        )

    return explicit_unique


def resolve_outputs_publish(spec: dict[str, Any]) -> list[str]:
    raw_outputs = spec.get("outputs")
    if raw_outputs is None:
        return []

    if not isinstance(raw_outputs, dict):
        raise ValueError("spec.outputs must be a mapping when set")

    raw_publish = raw_outputs.get("publish")
    if raw_publish is None:
        return []

    if not isinstance(raw_publish, list):
        raise ValueError("spec.outputs.publish must be a list when set")

    publish: list[str] = []
    seen: set[str] = set()

    for item in raw_publish:
        if not isinstance(item, str):
            raise ValueError("spec.outputs.publish entries must be strings")

        key = item.strip()
        if not key:
            continue

        if not _OUTPUT_KEY_RE.fullmatch(key):
            raise ValueError(f"invalid output key in spec.outputs.publish: {key!r}")

        if key in seen:
            continue

        seen.add(key)
        publish.append(key)

    return publish


def resolve_execution_hooks(raw_exec: dict[str, Any]) -> dict[str, Any]:
    raw_hooks = raw_exec.get("hooks")
    if raw_hooks is None:
        return {}

    if not isinstance(raw_hooks, dict):
        raise ValueError("spec.execution.hooks must be a mapping when set")

    out: dict[str, Any] = {}

    raw_export = raw_hooks.get("export_infra")
    if raw_export is None:
        return out

    if isinstance(raw_export, bool):
        out["export_infra"] = {
            "enabled": bool(raw_export),
            "target": "",
            "strict": False,
            "push_to_netbox": False,
        }
        return out

    if not isinstance(raw_export, dict):
        raise ValueError("spec.execution.hooks.export_infra must be a bool or mapping")

    allowed_keys = {"enabled", "target", "strict", "push_to_netbox"}
    unknown = sorted([k for k in raw_export.keys() if str(k) not in allowed_keys])
    if unknown:
        raise ValueError(
            f"spec.execution.hooks.export_infra has unknown keys: {', '.join(unknown)}"
        )

    enabled = as_bool(raw_export.get("enabled"), default=False)
    target = str(raw_export.get("target") or "").strip()
    strict = as_bool(raw_export.get("strict"), default=False)
    push_to_netbox = as_bool(raw_export.get("push_to_netbox"), default=False)

    if push_to_netbox and not enabled:
        raise ValueError("spec.execution.hooks.export_infra.push_to_netbox requires enabled=true")

    out["export_infra"] = {
        "enabled": enabled,
        "target": target,
        "strict": strict,
        "push_to_netbox": push_to_netbox,
    }

    return out


def resolve_dependencies(
    spec: dict[str, Any],
    module_ref: str,
    state_dir: Path | None,
    *,
    assumed_state_ok: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    raw_deps = spec.get("dependencies")
    if raw_deps is None:
        return {}, [], []

    if not isinstance(raw_deps, list):
        raise ValueError("spec.dependencies must be a list when set")

    if not raw_deps:
        return {}, [], []

    if state_dir is None:
        raise ValueError("spec.dependencies requires runtime state_dir")

    imported_inputs: dict[str, Any] = {}
    resolved_dependencies: list[dict[str, Any]] = []
    warnings: list[str] = []

    for idx, dep in enumerate(raw_deps, start=1):
        if not isinstance(dep, dict):
            raise ValueError(f"spec.dependencies[{idx}] must be a mapping")

        dep_ref = normalize_module_ref(str(dep.get("module_ref") or "").strip())
        if not dep_ref:
            raise ValueError(f"spec.dependencies[{idx}].module_ref is required")

        if dep_ref == module_ref:
            raise ValueError("spec.dependencies cannot reference the same module_ref")

        required = as_bool(dep.get("required"), default=True)

        raw_imports = dep.get("imports")
        if not isinstance(raw_imports, dict) or not raw_imports:
            raise ValueError(f"spec.dependencies[{idx}].imports must be a non-empty mapping")

        imports: dict[str, str] = {}
        for output_key, to_input in raw_imports.items():
            if not isinstance(output_key, str) or not output_key.strip():
                raise ValueError(f"spec.dependencies[{idx}].imports keys must be non-empty strings")
            if not isinstance(to_input, str) or not to_input.strip():
                raise ValueError(f"spec.dependencies[{idx}].imports[{output_key!r}] must be a non-empty string")

            key = output_key.strip()
            if not _OUTPUT_KEY_RE.fullmatch(key):
                raise ValueError(f"invalid dependency output key: {key!r}")

            parse_input_path(to_input.strip())
            imports[key] = to_input.strip()

        state_path = module_state_path(state_dir, dep_ref)

        try:
            dep_state = read_module_state(state_dir, dep_ref)
        except Exception as e:
            msg = f"dependency state unavailable for {dep_ref}: {e}"
            if required and (assumed_state_ok is None or dep_ref not in assumed_state_ok):
                raise ValueError(msg) from e

            warnings.append(msg)
            resolved_dependencies.append(
                {
                    "module_ref": dep_ref,
                    "required": required,
                    "resolved": False,
                    "state_path": str(state_path),
                    "imports": imports,
                }
            )
            continue

        dep_outputs = dep_state.get("outputs")
        if not isinstance(dep_outputs, dict):
            dep_outputs = {}

        missing_outputs: list[str] = []
        imported_count = 0

        for output_key, to_input in imports.items():
            ok, value = try_get_nested(dep_outputs, output_key)
            if not ok:
                missing_outputs.append(output_key)
                continue

            set_nested(imported_inputs, parse_input_path(to_input), value)
            imported_count += 1

        if missing_outputs:
            msg = f"dependency outputs missing for {dep_ref}: {', '.join(sorted(missing_outputs))}"
            if required:
                raise ValueError(msg)
            warnings.append(msg)

        resolved_dependencies.append(
            {
                "module_ref": dep_ref,
                "required": required,
                "resolved": imported_count > 0,
                "state_path": str(state_path),
                "imports": imports,
                "imported": imported_count,
            }
        )

    return imported_inputs, resolved_dependencies, warnings
