"""
Shared helpers for hyops.commands.apply.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from hyops.runtime.coerce import as_bool
from hyops.runtime.module_state import read_module_state
from hyops.runtime.refs import module_id_from_ref, normalize_module_ref
from hyops.runtime.state import write_yaml_atomic


def evidence_root(paths, out_dir: str | None, module_ref: str) -> Path:
    module_id = module_id_from_ref(module_ref)
    if not module_id:
        raise SystemExit("ERR: invalid module ref (cannot derive module_id)")

    if out_dir:
        return Path(out_dir).expanduser().resolve() / "module" / module_id

    return paths.logs_dir / "module" / module_id


def progress_log_hint(driver_ref: str, evidence_dir: Path) -> str:
    token = str(driver_ref or "").strip().lower()
    if token == "iac/terragrunt":
        return str((evidence_dir / "terragrunt.log").resolve())
    if token == "config/ansible":
        return str((evidence_dir / "ansible.log").resolve())
    if token == "images/packer":
        return str((evidence_dir / "packer.log").resolve())
    return str(evidence_dir)


def driver_outputs(result: dict[str, Any]) -> dict[str, Any]:
    normalized = result.get("normalized_outputs")
    if not isinstance(normalized, dict):
        return {}

    for key in ("published_outputs", "outputs", "terragrunt_outputs"):
        raw = normalized.get(key)
        if isinstance(raw, dict):
            return dict(raw)
    return {}


def select_published_outputs(all_outputs: dict[str, Any], publish: list[str]) -> dict[str, Any]:
    if not publish:
        return {}

    out: dict[str, Any] = {}
    for key in publish:
        if key in all_outputs:
            out[key] = all_outputs.get(key)
    return out


def _first_nfs_server(raw_vms: dict[str, Any]) -> str:
    for logical_name in sorted(raw_vms.keys()):
        vm_payload = raw_vms.get(logical_name)
        if not isinstance(vm_payload, dict):
            continue
        configured = str(vm_payload.get("ipv4_configured_primary") or "").strip()
        if configured:
            return configured.split("/", 1)[0].strip()
        addresses = vm_payload.get("ipv4_addresses")
        if isinstance(addresses, list):
            for group in addresses:
                if not isinstance(group, list):
                    continue
                for candidate in group:
                    token = str(candidate or "").strip()
                    if token and token != "127.0.0.1":
                        return token
    return ""


def normalize_published_outputs(module_ref: str, outputs: dict[str, Any]) -> dict[str, Any]:
    """Normalize published outputs for stable downstream/operator semantics."""
    if not outputs:
        return {}

    out = deepcopy(outputs)
    normalized_ref = normalize_module_ref(module_ref)
    if normalized_ref not in ("platform/onprem/platform-vm", "platform/gcp/platform-vm", "platform/onprem/nfs-appliance"):
        return out

    raw_vms = out.get("vms")
    if not isinstance(raw_vms, dict) or not raw_vms:
        return out

    vm_keys: list[str] = []
    vm_names: list[str] = []
    for logical_name, vm_payload in raw_vms.items():
        logical = str(logical_name or "").strip()
        if not logical:
            continue
        vm_keys.append(logical)
        physical = ""
        if isinstance(vm_payload, dict):
            physical = str(vm_payload.get("vm_name") or "").strip()
        vm_names.append(physical or logical)

    if vm_keys:
        out["vm_keys"] = vm_keys
    if vm_names:
        # vm_names should reflect the actual physical resource names presented to operators.
        out["vm_names"] = vm_names
    if normalized_ref == "platform/onprem/nfs-appliance":
        nfs_server = _first_nfs_server(raw_vms)
        if nfs_server:
            out["nfs_server"] = nfs_server
    return out


def build_input_contract(inputs: dict[str, Any]) -> dict[str, Any]:
    """Persist small, non-secret contract metadata for downstream consumers."""
    out: dict[str, Any] = {}

    raw_addressing = inputs.get("addressing")
    if isinstance(raw_addressing, dict):
        mode = str(raw_addressing.get("mode") or "").strip().lower()
        if mode in ("static", "ipam"):
            out["addressing_mode"] = mode

        raw_ipam = raw_addressing.get("ipam")
        if isinstance(raw_ipam, dict):
            provider = str(raw_ipam.get("provider") or "").strip().lower()
            if provider:
                out["ipam_provider"] = provider

    require_ipam = inputs.get("require_ipam")
    if isinstance(require_ipam, bool):
        out["require_ipam"] = require_ipam

    inventory_state_ref = str(inputs.get("inventory_state_ref") or "").strip()
    if inventory_state_ref:
        out["inventory_state_ref"] = inventory_state_ref

    project_state_ref = str(inputs.get("project_state_ref") or "").strip()
    if project_state_ref:
        out["project_state_ref"] = project_state_ref

    network_state_ref = str(inputs.get("network_state_ref") or "").strip()
    if network_state_ref:
        out["network_state_ref"] = network_state_ref

    router_state_ref = str(inputs.get("router_state_ref") or "").strip()
    if router_state_ref:
        out["router_state_ref"] = router_state_ref

    inventory_requires_ipam = inputs.get("inventory_requires_ipam")
    if isinstance(inventory_requires_ipam, bool):
        out["inventory_requires_ipam"] = inventory_requires_ipam

    for key in ("provider_kind", "nfs_export_path", "snapshot_profile", "backup_profile"):
        raw = str(inputs.get(key) or "").strip()
        if raw:
            out[key] = raw

    raw_mount_options = inputs.get("nfs_mount_options")
    if isinstance(raw_mount_options, list):
        normalized_mount_options: list[str] = []
        for item in raw_mount_options:
            token = str(item or "").strip()
            if token:
                normalized_mount_options.append(token)
        if normalized_mount_options:
            out["nfs_mount_options"] = normalized_mount_options

    return out


_INTERNAL_INPUT_KEYS = {
    "hyops_lifecycle_command",
    "hyops_module_ref",
    "hyops_outputs_file",
    "hyops_run_id",
    "hyops_runtime_root",
    "_hyops_lifecycle_command",
}

_SENSITIVE_KEY_TOKENS = (
    "password",
    "secret",
    "token",
    "api_key",
    "account_key",
    "secret_access_key",
    "access_key",
    "sa_json",
)


def rerun_inputs_path(
    config_dir: Path,
    module_ref: str,
    *,
    state_instance: str | None = None,
) -> Path:
    module_id = module_id_from_ref(module_ref)
    if not module_id:
        raise ValueError(f"invalid module_ref: {module_ref!r}")

    base = config_dir / "modules" / module_id
    if state_instance:
        return base / "instances" / f"{state_instance}.inputs.yml"
    return base / "latest.inputs.yml"


def _is_sensitive_key(raw_key: str) -> bool:
    token = str(raw_key or "").strip().lower()
    if not token:
        return False
    if token.endswith("_env") or token.endswith("_file") or token.endswith("_path"):
        return False
    return any(part in token for part in _SENSITIVE_KEY_TOKENS)


def _sanitize_nested(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key in _INTERNAL_INPUT_KEYS or key.startswith("_hyops_"):
                continue
            if _is_sensitive_key(key):
                continue
            out[key] = _sanitize_nested(raw_value)
        return out
    if isinstance(value, list):
        return [_sanitize_nested(item) for item in value]
    return deepcopy(value)


def sanitize_rerun_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Persist operator-meaningful inputs while stripping runtime-only and derived keys."""
    sanitized = _sanitize_nested(inputs)
    if not isinstance(sanitized, dict):
        return {}

    if str(sanitized.get("target_state_ref") or "").strip():
        sanitized.pop("target_host", None)

    if str(sanitized.get("inventory_state_ref") or "").strip():
        sanitized.pop("inventory_groups", None)

    if str(sanitized.get("db_state_ref") or "").strip():
        for key in ("db_host", "db_port", "db_name", "db_user", "db_password_env"):
            sanitized.pop(key, None)

    for prefix in ("source", "target"):
        if str(sanitized.get(f"{prefix}_db_state_ref") or "").strip():
            for key in ("db_host", "db_port", "db_name", "db_user", "db_password_env"):
                sanitized.pop(f"{prefix}_{key}", None)

    if str(sanitized.get("project_state_ref") or "").strip():
        sanitized.pop("project_id", None)

    if str(sanitized.get("network_state_ref") or "").strip():
        sanitized.pop("private_network", None)
        sanitized.pop("network", None)
        sanitized.pop("network_self_link", None)
        if str(sanitized.get("subnetwork_output_key") or "").strip():
            sanitized.pop("subnetwork", None)
        raw_subnetwork_output_keys = sanitized.get("subnetwork_output_keys")
        if isinstance(raw_subnetwork_output_keys, list) and raw_subnetwork_output_keys:
            sanitized.pop("subnetwork_self_links", None)

    if str(sanitized.get("router_state_ref") or "").strip():
        sanitized.pop("router_name", None)

    if sanitized.get("ssh_keys_from_init") is True:
        sanitized.pop("ssh_keys", None)

    repo_fields = (
        "backend",
        "s3_bucket",
        "s3_endpoint",
        "s3_region",
        "s3_uri_style",
        "gcs_bucket",
        "gcs_sa_dest",
        "azure_storage_account",
        "azure_container",
    )
    if str(sanitized.get("repo_state_ref") or "").strip():
        for key in repo_fields:
            sanitized.pop(key, None)

    if str(sanitized.get("secondary_repo_state_ref") or "").strip():
        for key in repo_fields:
            sanitized.pop(f"secondary_{key}", None)

    return sanitized


def persist_rerun_inputs(
    config_dir: Path,
    module_ref: str,
    inputs: dict[str, Any],
    *,
    state_instance: str | None = None,
) -> Path:
    path = rerun_inputs_path(config_dir, module_ref, state_instance=state_instance)
    payload = sanitize_rerun_inputs(inputs)
    write_yaml_atomic(path, payload, mode=0o600, sort_keys=False)
    return path


def merge_template_image_outputs(
    state_dir: Path,
    module_ref: str,
    outputs: dict[str, Any],
    *,
    state_instance: str | None = None,
) -> dict[str, Any]:
    """Preserve template maps across multiple template-image runs in the same env."""
    if normalize_module_ref(module_ref) != "core/onprem/template-image":
        return outputs

    if not isinstance(outputs, dict) or not outputs:
        return outputs

    try:
        existing = read_module_state(state_dir, module_ref, state_instance=state_instance)
    except Exception:
        return outputs

    existing_outputs = existing.get("outputs")
    if not isinstance(existing_outputs, dict) or not existing_outputs:
        return outputs

    merged = dict(outputs)
    for key in ("template_vm_ids", "templates"):
        old = existing_outputs.get(key)
        new = merged.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            tmp = dict(old)
            tmp.update(new)
            merged[key] = tmp
        elif isinstance(old, dict) and key not in merged:
            merged[key] = dict(old)
    return merged


def load_module_spec(module_root: Path, module_ref: str) -> dict[str, Any]:
    ref = normalize_module_ref(module_ref)
    if not ref:
        raise ValueError(f"invalid module_ref: {module_ref!r}")

    spec_path = (module_root / ref / "spec.yml").resolve()
    if not spec_path.exists():
        raise FileNotFoundError(f"spec not found: {spec_path}")

    payload = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"invalid YAML object: {spec_path}")
    return payload


def required_dependencies(module_root: Path, module_ref: str) -> list[str]:
    spec = load_module_spec(module_root, module_ref)
    raw_deps = spec.get("dependencies")
    if raw_deps is None:
        return []
    if not isinstance(raw_deps, list):
        raise ValueError("spec.dependencies must be a list when set")

    out: list[str] = []
    seen: set[str] = set()
    for idx, dep in enumerate(raw_deps, start=1):
        if not isinstance(dep, dict):
            raise ValueError(f"spec.dependencies[{idx}] must be a mapping")

        dep_ref = normalize_module_ref(str(dep.get("module_ref") or "").strip())
        if not dep_ref:
            raise ValueError(f"spec.dependencies[{idx}].module_ref is required")

        required = as_bool(dep.get("required"), default=True)
        if not required:
            continue

        if dep_ref in seen:
            continue
        seen.add(dep_ref)
        out.append(dep_ref)
    return out


def dependency_order(module_root: Path, root_module_ref: str) -> list[str]:
    root = normalize_module_ref(root_module_ref)
    if not root:
        raise ValueError("module_ref is required")

    visiting: list[str] = []
    visited: set[str] = set()
    ordered: list[str] = []

    def dfs(ref: str) -> None:
        if ref in visited:
            return
        if ref in visiting:
            cycle = " -> ".join([*visiting, ref])
            raise ValueError(f"dependency cycle detected: {cycle}")

        visiting.append(ref)
        for dep_ref in required_dependencies(module_root, ref):
            dfs(dep_ref)
        visiting.pop()

        visited.add(ref)
        if ref != root:
            ordered.append(ref)

    dfs(root)
    return ordered


def module_state_ok(state_dir: Path, module_ref: str) -> bool:
    try:
        payload = read_module_state(state_dir, module_ref)
    except Exception:
        return False

    status = str(payload.get("status") or "").strip().lower()
    return status == "ok"


def assert_safe_gcp_object_repo_slot(
    state_dir: Path,
    module_ref: str,
    inputs: dict[str, Any],
    *,
    state_instance: str | None = None,
) -> None:
    ref = normalize_module_ref(module_ref)
    if ref not in ("org/gcp/object-repo", "org/gcp/pgbackrest-repo"):
        return

    desired_bucket = str(inputs.get("bucket_name") or "").strip()
    if not desired_bucket:
        return

    try:
        existing = read_module_state(state_dir, module_ref, state_instance=state_instance)
    except Exception:
        return

    status = str(existing.get("status") or "").strip().lower()
    if status != "ok":
        return

    outputs = existing.get("outputs")
    if not isinstance(outputs, dict):
        return

    existing_bucket = str(
        outputs.get("repo_bucket_name") or outputs.get("bucket_name") or ""
    ).strip()
    if not existing_bucket or existing_bucket == desired_bucket:
        return

    slot_ref = ref if not state_instance else f"{ref}#{state_instance}"
    raise ValueError(
        f"refusing bucket rename for existing state slot {slot_ref}: "
        f"current bucket={existing_bucket!r}, requested bucket={desired_bucket!r}. "
        "GCS buckets are immutable at this slot in HyOps because rename requires replacement "
        "and the existing repository may contain data. Reuse the current bucket name, destroy "
        "the slot after draining data, or use a new --state-instance for a separate repository."
    )


def dependency_inputs_file(module_ref: str, deps_inputs_dir: Path | None) -> Path | None:
    if deps_inputs_dir is None:
        return None

    module_id = module_id_from_ref(module_ref)
    if not module_id:
        return None

    candidates = [
        deps_inputs_dir / f"{module_id}.yml",
        deps_inputs_dir / f"{module_id}.yaml",
        deps_inputs_dir / module_ref / "inputs.yml",
        deps_inputs_dir / module_ref / "inputs.yaml",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None
