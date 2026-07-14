"""Blueprint schema loading and validation helpers."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
import yaml

from hyops.runtime.refs import normalize_module_ref

from .common import as_mapping, as_non_empty_string, bool_field
from .constants import (
    ACTION_SET,
    ADDRESSING_MODE_SET,
    AUTHORITY_SET,
    BLUEPRINT_REF_RE,
    MODE_SET,
    PHASE_SET,
    STEP_ID_RE,
)


def resolve_blueprint_file(ref: str, file_path: str, blueprints_root: Path) -> Path:
    explicit = str(file_path or "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"blueprint file not found: {path}")
        return path

    blueprint_ref = str(ref or "").strip()
    if not blueprint_ref:
        raise ValueError("either --ref or --file is required")

    if not BLUEPRINT_REF_RE.fullmatch(blueprint_ref):
        raise ValueError(
            "blueprint ref must match <scope>/<name>@<version>, e.g. onprem/eve-ng@v1"
        )

    base = (blueprints_root / blueprint_ref).resolve()
    for name in ("blueprint.yml", "blueprint.yaml"):
        candidate = base / name
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"blueprint file not found under: {base}. "
        "If the ref is valid in your source checkout, refresh the installed HybridOps payload "
        "(for example rerun install.sh) or use the repo-local CLI until the install is updated."
    )


def load_blueprint(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"invalid YAML object: {path}")
    return payload


def module_ref_field(value: Any, field: str) -> str:
    normalized = normalize_module_ref(as_non_empty_string(value, field))
    if not normalized:
        raise ValueError(f"{field} is invalid")
    return normalized


def module_ref_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(value, start=1):
        ref = module_ref_field(item, f"{field}[{idx}]")
        if ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return out


def validate_policy(raw_policy: Any) -> dict[str, Any]:
    defaults = {
        "fail_fast": True,
        "evidence_required": True,
        "ipam_authority": "none",
        "netbox_live_api_check": False,
    }
    if raw_policy is None:
        return defaults

    policy = as_mapping(raw_policy, "policy")
    allowed = {"fail_fast", "evidence_required", "ipam_authority", "netbox_live_api_check"}
    unknown = sorted([str(k) for k in policy.keys() if str(k) not in allowed])
    if unknown:
        raise ValueError(f"policy has unknown keys: {', '.join(unknown)}")

    out = dict(defaults)
    if "fail_fast" in policy:
        out["fail_fast"] = bool_field(policy.get("fail_fast"), "policy.fail_fast")
    if "evidence_required" in policy:
        out["evidence_required"] = bool_field(
            policy.get("evidence_required"),
            "policy.evidence_required",
        )
    if "ipam_authority" in policy:
        authority = as_non_empty_string(policy.get("ipam_authority"), "policy.ipam_authority").lower()
        if authority not in AUTHORITY_SET:
            raise ValueError(
                f"policy.ipam_authority must be one of: {', '.join(sorted(AUTHORITY_SET))}"
            )
        out["ipam_authority"] = authority
    if "netbox_live_api_check" in policy:
        out["netbox_live_api_check"] = bool_field(
            policy.get("netbox_live_api_check"),
            "policy.netbox_live_api_check",
        )
    return out


def topological_order(steps: list[dict[str, Any]]) -> list[str]:
    by_id = {s["id"]: s for s in steps}
    visiting: list[str] = []
    visited: set[str] = set()
    order: list[str] = []

    def dfs(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            cycle = " -> ".join([*visiting, step_id])
            raise ValueError(f"blueprint dependency cycle detected: {cycle}")

        visiting.append(step_id)
        for dep_id in by_id[step_id]["requires"]:
            dfs(dep_id)
        visiting.pop()

        visited.add(step_id)
        order.append(step_id)

    for step in steps:
        dfs(step["id"])

    return order


def validate_blueprint(spec: dict[str, Any], path: Path) -> dict[str, Any]:
    kind = as_non_empty_string(spec.get("kind"), "kind")
    if kind != "BlueprintSpec":
        raise ValueError("kind must be BlueprintSpec")

    as_non_empty_string(spec.get("api_version"), "api_version")

    blueprint_ref = as_non_empty_string(spec.get("blueprint_ref"), "blueprint_ref")
    if not BLUEPRINT_REF_RE.fullmatch(blueprint_ref):
        raise ValueError(
            "blueprint_ref must match <scope>/<name>@<version>, e.g. onprem/eve-ng@v1"
        )

    mode = str(spec.get("mode") or "hybrid").strip().lower()
    if mode not in MODE_SET:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODE_SET))}")

    metadata = spec.get("metadata")
    if metadata is not None:
        as_mapping(metadata, "metadata")
    policy = validate_policy(spec.get("policy"))
    access: dict[str, Any] = {}
    if spec.get("access") is not None:
        raw_access = as_mapping(spec.get("access"), "access")
        access_type = as_non_empty_string(raw_access.get("type"), "access.type")
        if access_type not in {
            "direct-http",
            "ssh-forward",
            "ssh-tcp-forward",
            "gcp-iap-http",
            "gcp-iap-ssh-forward",
        }:
            raise ValueError(
                "access.type must be direct-http, ssh-forward, ssh-tcp-forward, "
                "gcp-iap-http, or gcp-iap-ssh-forward"
            )
        access = {
            "type": access_type,
            "state_ref": as_non_empty_string(
                raw_access.get("state_ref"), "access.state_ref"
            ),
            "remote_port": int(raw_access.get("remote_port") or 80),
            "local_port": int(raw_access.get("local_port") or 0),
            "path": str(raw_access.get("path") or "/").strip() or "/",
            "open_browser": bool(raw_access.get("open_browser", True)),
            "ssh_user": str(raw_access.get("ssh_user") or "").strip(),
            "ssh_key_file": str(raw_access.get("ssh_key_file") or "").strip(),
            "native_console_mode": str(
                raw_access.get("native_console_mode") or ""
            ).strip(),
            "guest_network_label": str(
                raw_access.get("guest_network_label") or ""
            ).strip(),
            "guest_gateway": str(raw_access.get("guest_gateway") or "").strip(),
            "guest_dhcp_range": str(
                raw_access.get("guest_dhcp_range") or ""
            ).strip(),
            "offer_destroy_on_close": bool_field(
                raw_access.get("offer_destroy_on_close"),
                "access.offer_destroy_on_close",
            ),
        }
        if not 1 <= access["remote_port"] <= 65535:
            raise ValueError("access.remote_port must be between 1 and 65535")
        if access["local_port"] and not 1 <= access["local_port"] <= 65535:
            raise ValueError("access.local_port must be between 1 and 65535")
        if access_type in {
            "ssh-forward",
            "ssh-tcp-forward",
            "gcp-iap-ssh-forward",
        }:
            if not access["ssh_user"]:
                raise ValueError(
                    "access.ssh_user is required for SSH-forward access"
                )
            if not access["ssh_key_file"]:
                raise ValueError(
                    "access.ssh_key_file is required for SSH-forward access"
                )
        if access["native_console_mode"] not in {"", "eve-ng-qemu"}:
            raise ValueError(
                "access.native_console_mode must be eve-ng-qemu when set"
            )
        guest_fields = [
            access["guest_network_label"],
            access["guest_gateway"],
            access["guest_dhcp_range"],
        ]
        if any(guest_fields) and not all(guest_fields):
            raise ValueError(
                "access guest network guidance requires guest_network_label, "
                "guest_gateway, and guest_dhcp_range"
            )

    archive_before_destroy: dict[str, Any] = {}
    if spec.get("archive_before_destroy") is not None:
        raw_archive = as_mapping(
            spec.get("archive_before_destroy"), "archive_before_destroy"
        )
        allowed = {"module_ref", "state_instance", "inputs"}
        unknown = sorted(str(key) for key in raw_archive if str(key) not in allowed)
        if unknown:
            raise ValueError(
                "archive_before_destroy has unknown keys: " + ", ".join(unknown)
            )
        archive_inputs = raw_archive.get("inputs")
        if archive_inputs is not None:
            archive_inputs = as_mapping(
                archive_inputs, "archive_before_destroy.inputs"
            )
        archive_before_destroy = {
            "module_ref": module_ref_field(
                raw_archive.get("module_ref"),
                "archive_before_destroy.module_ref",
            ),
            "state_instance": as_non_empty_string(
                raw_archive.get("state_instance"),
                "archive_before_destroy.state_instance",
            ),
            "inputs": archive_inputs if isinstance(archive_inputs, dict) else {},
        }

    raw_steps = spec.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("steps must be a non-empty list")

    steps: list[dict[str, Any]] = []
    step_ids: set[str] = set()

    for idx, raw in enumerate(raw_steps, start=1):
        step = as_mapping(raw, f"steps[{idx}]")
        step_id = as_non_empty_string(step.get("id"), f"steps[{idx}].id")
        if not STEP_ID_RE.fullmatch(step_id):
            raise ValueError(f"steps[{idx}].id has invalid format: {step_id!r}")
        if step_id in step_ids:
            raise ValueError(f"duplicate step id: {step_id}")
        step_ids.add(step_id)

        module_ref = module_ref_field(step.get("module_ref"), f"steps[{idx}].module_ref")
        execution_profile = str(step.get("execution_profile") or "").strip()
        if execution_profile and not re.fullmatch(
            r"[a-z0-9][a-z0-9@._-]*", execution_profile
        ):
            raise ValueError(f"steps[{idx}].execution_profile has invalid format")

        action = str(step.get("action") or "deploy").strip().lower()
        if action not in ACTION_SET:
            raise ValueError(
                f"steps[{idx}].action must be one of: {', '.join(sorted(ACTION_SET))}"
            )

        phase = str(step.get("phase") or "").strip().lower()
        if not phase:
            if mode == "bootstrap":
                phase = "bootstrap"
            elif mode == "authoritative":
                phase = "authoritative"
            else:
                phase = "operations"
        if phase not in PHASE_SET:
            raise ValueError(f"steps[{idx}].phase must be one of: {', '.join(sorted(PHASE_SET))}")

        raw_requires = step.get("requires")
        requires: list[str] = []
        if raw_requires is not None:
            if not isinstance(raw_requires, list):
                raise ValueError(f"steps[{idx}].requires must be a list when set")
            seen_req: set[str] = set()
            for r_idx, ref in enumerate(raw_requires, start=1):
                req_id = as_non_empty_string(ref, f"steps[{idx}].requires[{r_idx}]")
                if req_id in seen_req:
                    continue
                seen_req.add(req_id)
                requires.append(req_id)

        inputs = step.get("inputs")
        if inputs is not None:
            as_mapping(inputs, f"steps[{idx}].inputs")

        inputs_file = step.get("inputs_file")
        if inputs_file is not None:
            as_non_empty_string(inputs_file, f"steps[{idx}].inputs_file")
        state_instance = ""
        if step.get("state_instance") is not None:
            from hyops.runtime.module_state import normalize_state_instance

            token = as_non_empty_string(step.get("state_instance"), f"steps[{idx}].state_instance")
            norm_token = normalize_state_instance(token)
            state_instance = norm_token or ""

        contracts: dict[str, Any] = {
            "addressing_mode": "static",
            "requires_module_state_ok": [],
            "requires_authority": "none",
        }
        raw_contracts = step.get("contracts")
        if raw_contracts is not None:
            contract_map = as_mapping(raw_contracts, f"steps[{idx}].contracts")
            allowed = {"addressing_mode", "requires_module_state_ok", "requires_authority"}
            unknown = sorted([str(k) for k in contract_map.keys() if str(k) not in allowed])
            if unknown:
                raise ValueError(
                    f"steps[{idx}].contracts has unknown keys: {', '.join(unknown)}"
                )

            if "addressing_mode" in contract_map:
                addressing_mode = as_non_empty_string(
                    contract_map.get("addressing_mode"),
                    f"steps[{idx}].contracts.addressing_mode",
                ).lower()
                if addressing_mode not in ADDRESSING_MODE_SET:
                    raise ValueError(
                        f"steps[{idx}].contracts.addressing_mode must be one of: "
                        f"{', '.join(sorted(ADDRESSING_MODE_SET))}"
                    )
                contracts["addressing_mode"] = addressing_mode

            if "requires_module_state_ok" in contract_map:
                contracts["requires_module_state_ok"] = module_ref_list(
                    contract_map.get("requires_module_state_ok"),
                    f"steps[{idx}].contracts.requires_module_state_ok",
                )

            if "requires_authority" in contract_map:
                authority = as_non_empty_string(
                    contract_map.get("requires_authority"),
                    f"steps[{idx}].contracts.requires_authority",
                ).lower()
                if authority not in AUTHORITY_SET:
                    raise ValueError(
                        f"steps[{idx}].contracts.requires_authority must be one of: "
                        f"{', '.join(sorted(AUTHORITY_SET))}"
                    )
                contracts["requires_authority"] = authority

        if (
            contracts["addressing_mode"] == "ipam"
            and contracts["requires_authority"] != "netbox"
        ):
            raise ValueError(
                f"steps[{idx}] uses addressing_mode=ipam and must set contracts.requires_authority=netbox"
            )

        steps.append(
            {
                "id": step_id,
                "module_ref": module_ref,
                "execution_profile": execution_profile,
                "action": action,
                "phase": phase,
                "requires": requires,
                "with_deps": bool_field(step.get("with_deps"), f"steps[{idx}].with_deps"),
                "skip_if_state_ok": bool_field(
                    step.get("skip_if_state_ok"),
                    f"steps[{idx}].skip_if_state_ok",
                ),
                "verify_state_on_skip": bool_field(
                    step.get("verify_state_on_skip"),
                    f"steps[{idx}].verify_state_on_skip",
                ),
                "retain_on_destroy": bool_field(
                    step.get("retain_on_destroy"),
                    f"steps[{idx}].retain_on_destroy",
                ),
                "optional": bool_field(step.get("optional"), f"steps[{idx}].optional"),
                "inputs": inputs if isinstance(inputs, dict) else None,
                "inputs_file": str(inputs_file).strip() if isinstance(inputs_file, str) else "",
                "state_instance": state_instance,
                "contracts": contracts,
            }
        )

    id_set = {s["id"] for s in steps}
    for step in steps:
        for req in step["requires"]:
            if req not in id_set:
                raise ValueError(f"step '{step['id']}' requires unknown step '{req}'")

    order = topological_order(steps)

    return {
        "path": str(path),
        "blueprint_ref": blueprint_ref,
        "mode": mode,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "policy": policy,
        "access": access,
        "archive_before_destroy": archive_before_destroy,
        "steps": steps,
        "order": order,
    }
