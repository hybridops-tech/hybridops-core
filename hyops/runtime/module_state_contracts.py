"""Runtime state contract resolution helpers.

purpose: Resolve target/inventory/database/repository contracts from upstream module state.
Architecture Decision: ADR-N/A (module resolution)
maintainer: HybridOps
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import ipaddress
import re
import yaml

from hyops.runtime.coerce import as_bool
from hyops.runtime.kv import read_kv_file
from hyops.runtime.gcp import normalize_billing_account_id
from hyops.runtime.readiness import read_marker
from hyops.runtime.module_inputs import try_get_nested
from hyops.runtime.refs import module_id_from_ref
from hyops.runtime.state import read_json
from hyops.runtime.module_state import (
    normalize_module_state_ref,
    read_module_state,
    split_module_state_ref,
)


_INPUT_SEG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_GCP_VM_ID_RE = re.compile(r"^projects/(?P<project>[^/]+)/zones/(?P<zone>[^/]+)/instances/(?P<name>[^/]+)$")
_PGHA_STATE_REFS = {"platform/postgresql-ha", "platform/onprem/postgresql-ha"}
_PGHA_BACKUP_STATE_REFS = {
    "platform/postgresql-ha-backup",
    "platform/onprem/postgresql-ha-backup",
}
_REPO_STATE_INSTANCE_REFS = {
    "org/aws/object-repo",
    "org/aws/pgbackrest-repo",
    "org/azure/object-repo",
    "org/azure/pgbackrest-repo",
    "org/gcp/object-repo",
    "org/gcp/pgbackrest-repo",
}


def _ready_repo_state_instances(state_root: Path, module_ref: str) -> list[str]:
    ref, instance = split_module_state_ref(module_ref)
    if instance or ref not in _REPO_STATE_INSTANCE_REFS:
        return []

    module_id = module_id_from_ref(ref)
    if not module_id:
        return []

    instances_dir = Path(state_root).expanduser().resolve() / "modules" / module_id / "instances"
    if not instances_dir.is_dir():
        return []

    ready: list[str] = []
    for candidate in sorted(instances_dir.glob("*.json")):
        try:
            payload = read_json(candidate)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status == "ok":
            ready.append(candidate.stem)
    return ready


def _infer_inventory_target_user_from_state(state: dict[str, Any]) -> str:
    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    for key in ("target_user", "control_user", "ssh_username"):
        token = str(outputs.get(key) or "").strip()
        if token and token != "root":
            return token

    raw_contract = state.get("input_contract")
    contract = raw_contract if isinstance(raw_contract, dict) else {}
    for key in ("target_user", "ssh_username"):
        token = str(contract.get(key) or "").strip()
        if token and token != "root":
            return token

    rerun_inputs_file = str(state.get("rerun_inputs_file") or "").strip()
    if not rerun_inputs_file:
        return ""

    try:
        rerun_path = Path(rerun_inputs_file).expanduser().resolve()
    except Exception:
        return ""
    if not rerun_path.is_file():
        return ""

    try:
        payload = yaml.safe_load(rerun_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""

    for key in ("target_user", "ssh_username"):
        token = str(payload.get(key) or "").strip()
        if token and token != "root":
            return token

    raw_readiness = payload.get("post_apply_ssh_readiness")
    readiness = raw_readiness if isinstance(raw_readiness, dict) else {}
    token = str(readiness.get("target_user") or "").strip()
    if token and token != "root":
        return token

    return ""


def _load_resolved_inputs_from_state(
    state: dict[str, Any],
    *,
    state_root: Path | None,
) -> dict[str, Any]:
    candidates: list[Path] = []

    resolved_inputs_file = str(state.get("resolved_inputs_file") or "").strip()
    if resolved_inputs_file:
        try:
            candidates.append(Path(resolved_inputs_file).expanduser().resolve())
        except Exception:
            pass

    evidence_dir = str(state.get("evidence_dir") or "").strip()
    if evidence_dir:
        try:
            candidates.append((Path(evidence_dir).expanduser().resolve() / "resolved.inputs.yml").resolve())
        except Exception:
            pass

    module_ref = str(state.get("module_ref") or "").strip()
    run_id = str(state.get("run_id") or "").strip()
    module_id = module_id_from_ref(module_ref) if module_ref else ""
    if state_root is not None and module_id and run_id:
        try:
            candidates.append((state_root.parent / "work" / module_id / run_id / "hyops.inputs.yml").resolve())
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
            return payload

    return {}


def _load_rerun_inputs_from_state(state: dict[str, Any]) -> dict[str, Any]:
    rerun_inputs_file = str(state.get("rerun_inputs_file") or "").strip()
    if not rerun_inputs_file:
        return {}

    try:
        rerun_path = Path(rerun_inputs_file).expanduser().resolve()
    except Exception:
        return {}
    if not rerun_path.is_file():
        return {}

    try:
        payload = yaml.safe_load(rerun_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _backfill_input_from_mapping(inputs: dict[str, Any], source: dict[str, Any], key: str) -> None:
    if key not in source:
        return

    current = inputs.get(key)
    if current is not None:
        if isinstance(current, str) and current.strip():
            return
        if isinstance(current, (dict, list)) and current:
            return
        if isinstance(current, bool):
            return
        if isinstance(current, int) and not isinstance(current, bool) and current != 0:
            return

    candidate = source.get(key)
    if candidate is None:
        return
    if isinstance(candidate, str) and not candidate.strip():
        return
    if isinstance(candidate, (dict, list)) and not candidate:
        return

    inputs[key] = candidate


def resolve_state_root_for_env_override(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    override_key: str,
) -> Path | None:
    """Resolve an alternate env state root under an explicit cross-env policy."""
    override_env = str(inputs.get(override_key) or "").strip()
    if not override_env:
        return state_root

    if state_root is None:
        raise ValueError(f"inputs.{override_key} requires runtime state_dir")

    try:
        envs_root = state_root.parent.parent
        candidate = (envs_root / override_env / "state").resolve()
        if not candidate.exists():
            raise ValueError(
                f"inputs.{override_key}={override_env!r} resolved state dir does not exist: {candidate}"
            )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"inputs.{override_key} is invalid: {override_env!r}") from exc

    current_env = str(state_root.parent.name or "").strip()
    if override_env == current_env or override_env.lower() == "shared":
        return candidate

    if as_bool(inputs.get("allow_cross_env_state"), default=False):
        return candidate

    raise ValueError(
        f"inputs.{override_key}={override_env!r} crosses env boundary from current env={current_env!r}. "
        "Same-env state resolution is the default, and 'shared' is the only normal cross-env authority. "
        "Set inputs.allow_cross_env_state=true only for controlled drills or migrations."
    )


def _infer_inventory_target_user_from_state(state: dict[str, Any]) -> str:
    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    for key in ("target_user", "control_user", "ssh_username"):
        token = str(outputs.get(key) or "").strip()
        if token and token != "root":
            return token

    raw_contract = state.get("input_contract")
    contract = raw_contract if isinstance(raw_contract, dict) else {}
    for key in ("target_user", "ssh_username"):
        token = str(contract.get(key) or "").strip()
        if token and token != "root":
            return token

    rerun_inputs_file = str(state.get("rerun_inputs_file") or "").strip()
    if not rerun_inputs_file:
        return ""

    try:
        rerun_path = Path(rerun_inputs_file).expanduser().resolve()
    except Exception:
        return ""
    if not rerun_path.is_file():
        return ""

    try:
        payload = yaml.safe_load(rerun_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""

    for key in ("target_user", "ssh_username"):
        token = str(payload.get(key) or "").strip()
        if token and token != "root":
            return token

    raw_readiness = payload.get("post_apply_ssh_readiness")
    readiness = raw_readiness if isinstance(raw_readiness, dict) else {}
    token = str(readiness.get("target_user") or "").strip()
    if token and token != "root":
        return token

    return ""


def ipv4_from_token(raw: Any) -> str | None:
    token = str(raw or "").strip()
    if not token:
        return None
    try:
        ip = ipaddress.ip_interface(token).ip if "/" in token else ipaddress.ip_address(token)
    except Exception:
        return None
    if not isinstance(ip, ipaddress.IPv4Address):
        return None
    if ip.is_loopback:
        return None
    return str(ip)


def pick_ipv4(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return ipv4_from_token(value)
    if isinstance(value, dict):
        # Common shape: {"address": "10.0.0.10/24", ...}
        if "address" in value:
            return pick_ipv4(value.get("address"))
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            picked = pick_ipv4(item)
            if picked:
                return picked
        return None
    return ipv4_from_token(value)


def resolve_vm_ipv4(outputs: dict[str, Any], *, vm_key: str) -> str | None:
    vms = outputs.get("vms")
    if isinstance(vms, dict) and vm_key in vms and isinstance(vms.get(vm_key), dict):
        vm = vms.get(vm_key) or {}
        for key in ("ipv4_address", "ipv4_configured_primary", "ipv4_addresses"):
            picked = pick_ipv4(vm.get(key))
            if picked:
                return picked

    for top_key in ("ipv4_configured_primary", "ipv4_addresses", "ipv4_addresses_all"):
        bucket = outputs.get(top_key)
        if isinstance(bucket, dict) and vm_key in bucket:
            picked = pick_ipv4(bucket.get(vm_key))
            if picked:
                return picked

    return None


def resolve_gcp_instance_contract(outputs: dict[str, Any], *, vm_key: str) -> dict[str, str]:
    vm_name = ""
    zone = ""
    project_id = ""

    vms = outputs.get("vms")
    if isinstance(vms, dict) and vm_key in vms and isinstance(vms.get(vm_key), dict):
        vm = vms.get(vm_key) or {}
        vm_name = str(vm.get("vm_name") or "").strip()
        zone = str(vm.get("zone") or "").strip()
        vm_id = str(vm.get("vm_id") or "").strip()
        if vm_id:
            match = _GCP_VM_ID_RE.fullmatch(vm_id)
            if match:
                if not vm_name:
                    vm_name = str(match.group("name") or "").strip()
                if not zone:
                    zone = str(match.group("zone") or "").strip()
                project_id = str(match.group("project") or "").strip()

    return {
        "gcp_iap_instance": vm_name,
        "gcp_iap_zone": zone,
        "gcp_iap_project_id": project_id,
    }


def resolve_vm_private_ipv4(outputs: dict[str, Any], *, vm_key: str) -> str | None:
    vms = outputs.get("vms")
    if isinstance(vms, dict) and vm_key in vms and isinstance(vms.get(vm_key), dict):
        vm = vms.get(vm_key) or {}
        for key in ("private_ipv4_address", "private_ip", "private_ipv4"):
            picked = pick_ipv4(vm.get(key))
            if picked:
                return picked
    return None


def resolve_vm_tags(outputs: dict[str, Any], *, vm_key: str) -> list[str]:
    vms = outputs.get("vms")
    if isinstance(vms, dict) and vm_key in vms and isinstance(vms.get(vm_key), dict):
        vm = vms.get(vm_key) or {}
        raw_tags = vm.get("tags")
        if isinstance(raw_tags, list):
            return [str(tag).strip() for tag in raw_tags if str(tag).strip()]

    bucket = outputs.get("tags")
    if isinstance(bucket, dict) and vm_key in bucket and isinstance(bucket.get(vm_key), list):
        return [str(tag).strip() for tag in bucket.get(vm_key) or [] if str(tag).strip()]

    return []


def resolve_target_host_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve inputs.target_host from a VM-producing module state when requested."""
    if str(inputs.get("target_host") or "").strip():
        return

    raw_ref = str(inputs.get("target_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        target_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.target_state_ref is invalid: {raw_ref!r}")

    vm_key = str(inputs.get("target_vm_key") or "").strip()
    if not vm_key:
        raise ValueError(
            "inputs.target_vm_key is required when inputs.target_state_ref is set and inputs.target_host is empty"
        )

    if state_root is None:
        raise ValueError("inputs.target_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, target_state_ref)
    except Exception as e:
        if assumed_state_ok is not None and target_state_ref in assumed_state_ok:
            inputs["target_host"] = str(inputs.get("target_host") or "0.0.0.0").strip() or "0.0.0.0"
            return
        raise ValueError(
            f"target_state_ref={target_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{target_state_ref}' or provide inputs.target_host explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        if assumed_state_ok is not None and target_state_ref in assumed_state_ok:
            # Blueprint preflight can "assume" upstream state will be ready by execution time.
            inputs["target_host"] = str(inputs.get("target_host") or "0.0.0.0").strip() or "0.0.0.0"
            return
        raise ValueError(
            f"target_state_ref={target_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{target_state_ref}' or provide inputs.target_host explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    picked = resolve_vm_ipv4(outputs, vm_key=vm_key)
    if picked:
        inputs["target_host"] = picked
        return

    if assumed_state_ok is not None and target_state_ref in assumed_state_ok:
        # Blueprint preflight: upstream module is planned in this run; delay
        # concrete host resolution until execution time.
        inputs["target_host"] = "0.0.0.0"
        return

    candidates: list[str] = []
    vms = outputs.get("vms")
    if isinstance(vms, dict):
        candidates = sorted([str(k) for k in vms.keys() if str(k)])
    raise ValueError(
        f"unable to resolve inputs.target_host from target_state_ref={target_state_ref} "
        f"for target_vm_key={vm_key!r}. "
        + (f"available vm keys: {', '.join(candidates)}" if candidates else "state does not publish outputs.vms")
    )


def resolve_inventory_groups_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve inputs.inventory_groups from upstream module state when requested."""
    existing = inputs.get("inventory_groups")
    if isinstance(existing, dict) and existing:
        return

    raw_ref = str(inputs.get("inventory_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        inventory_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.inventory_state_ref is invalid: {raw_ref!r}")

    if state_root is None:
        raise ValueError("inputs.inventory_state_ref requires runtime state_dir")

    raw_groups = inputs.get("inventory_vm_groups")
    lifecycle_command = str(inputs.get("_hyops_lifecycle_command") or "").strip().lower()

    def _placeholder_inventory_groups() -> dict[str, Any]:
        if not isinstance(raw_groups, dict) or not raw_groups:
            return {}
        out: dict[str, Any] = {}
        for raw_group, raw_vm_keys in raw_groups.items():
            group = str(raw_group or "").strip()
            if not group:
                raise ValueError("inputs.inventory_vm_groups keys must be non-empty strings")
            if not isinstance(raw_vm_keys, list) or not raw_vm_keys:
                raise ValueError(f"inputs.inventory_vm_groups[{group!r}] must be a non-empty list")

            hosts: list[dict[str, str]] = []
            for idx, raw_vm_key in enumerate(raw_vm_keys, start=1):
                vm_key = str(raw_vm_key or "").strip()
                if not vm_key:
                    raise ValueError(
                        f"inputs.inventory_vm_groups[{group!r}][{idx}] must be a non-empty string"
                    )
                hosts.append({"name": vm_key, "host": "0.0.0.0"})
            out[group] = hosts
        return out

    try:
        state = read_module_state(state_root, inventory_state_ref)
    except Exception as e:
        if assumed_state_ok is not None and inventory_state_ref in assumed_state_ok:
            inputs["inventory_groups"] = _placeholder_inventory_groups()
            return
        raise ValueError(
            f"inventory_state_ref={inventory_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{inventory_state_ref}' or provide explicit inputs.inventory_groups."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        if lifecycle_command == "destroy" and status in {"destroyed", "absent"}:
            inputs["inventory_groups"] = _placeholder_inventory_groups()
            return
        if assumed_state_ok is not None and inventory_state_ref in assumed_state_ok:
            # Blueprint preflight can "assume" upstream state will be ready by execution time.
            inputs["inventory_groups"] = _placeholder_inventory_groups()
            return
        raise ValueError(
            f"inventory_state_ref={inventory_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{inventory_state_ref}' or provide explicit inputs.inventory_groups."
        )

    inventory_requires_ipam = as_bool(inputs.get("inventory_requires_ipam"), default=False)
    if inventory_requires_ipam:
        inventory_base_ref, _inventory_instance = split_module_state_ref(inventory_state_ref)
        if inventory_base_ref not in ("platform/onprem/platform-vm", *_PGHA_STATE_REFS):
            raise ValueError(
                "inputs.inventory_requires_ipam=true currently requires "
                "inputs.inventory_state_ref=platform/onprem/platform-vm or platform/postgresql-ha"
            )

        if inventory_base_ref == "platform/onprem/platform-vm":
            raw_contract = state.get("input_contract")
            contract = raw_contract if isinstance(raw_contract, dict) else {}
            addressing_mode = str(contract.get("addressing_mode") or "").strip().lower()
            ipam_provider = str(contract.get("ipam_provider") or "").strip().lower()
            if addressing_mode != "ipam" or ipam_provider != "netbox":
                raise ValueError(
                    "inventory_state_ref=platform/onprem/platform-vm is not NetBox-IPAM managed. "
                    "Expected state.input_contract.addressing_mode=ipam and ipam_provider=netbox. "
                    "Re-apply upstream module 'platform/onprem/platform-vm' with "
                    "inputs.require_ipam=true and inputs.addressing.mode=ipam (provider=netbox)."
                )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    published_inventory_groups = outputs.get("inventory_groups")
    if isinstance(published_inventory_groups, dict) and published_inventory_groups:
        inventory_requires_ipam = as_bool(inputs.get("inventory_requires_ipam"), default=False)
        if inventory_requires_ipam:
            inventory_base_ref, _inventory_instance = split_module_state_ref(inventory_state_ref)
            if inventory_base_ref in _PGHA_STATE_REFS:
                raw_contract = state.get("input_contract")
                contract = raw_contract if isinstance(raw_contract, dict) else {}
                source_ref = str(contract.get("inventory_state_ref") or "").strip()
                source_requires_ipam = bool(contract.get("inventory_requires_ipam") is True)
                source_base_ref = ""
                if source_ref:
                    try:
                        source_base_ref, _source_instance = split_module_state_ref(source_ref)
                    except Exception:
                        source_base_ref = ""
                if source_base_ref != "platform/onprem/platform-vm" or not source_requires_ipam:
                    raise ValueError(
                        "inventory_state_ref=platform/postgresql-ha does not prove NetBox-IPAM provenance. "
                        "Expected state.input_contract.inventory_state_ref=platform/onprem/platform-vm[#instance] and "
                        "state.input_contract.inventory_requires_ipam=true."
                    )
            elif inventory_base_ref != "platform/onprem/platform-vm":
                raise ValueError(
                    "inputs.inventory_requires_ipam=true requires inventory state published either directly from "
                    "platform/onprem/platform-vm or transitively from platform/postgresql-ha."
                )

        inputs["inventory_groups"] = published_inventory_groups
        return

    if not isinstance(raw_groups, dict) or not raw_groups:
        inventory_base_ref, _inventory_instance = split_module_state_ref(inventory_state_ref)
        if inventory_base_ref in _PGHA_STATE_REFS:
            raise ValueError(
                "inventory_state_ref=platform/postgresql-ha does not yet publish outputs.inventory_groups. "
                "Re-apply upstream module 'platform/postgresql-ha' once to refresh its state contract, "
                "or provide explicit inputs.inventory_groups."
            )
        raise ValueError(
            "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set "
            "unless the referenced state already publishes outputs.inventory_groups"
        )

    out: dict[str, Any] = {}
    for raw_group, raw_vm_keys in raw_groups.items():
        group = str(raw_group or "").strip()
        if not group:
            raise ValueError("inputs.inventory_vm_groups keys must be non-empty strings")
        if not isinstance(raw_vm_keys, list) or not raw_vm_keys:
            raise ValueError(f"inputs.inventory_vm_groups[{group!r}] must be a non-empty list")

        hosts: list[dict[str, str]] = []
        for idx, raw_vm_key in enumerate(raw_vm_keys, start=1):
            vm_key = str(raw_vm_key or "").strip()
            if not vm_key:
                raise ValueError(f"inputs.inventory_vm_groups[{group!r}][{idx}] must be a non-empty string")
            picked = resolve_vm_ipv4(outputs, vm_key=vm_key)
            if not picked:
                if assumed_state_ok is not None and inventory_state_ref in assumed_state_ok:
                    hosts.append({"name": vm_key, "host": "0.0.0.0"})
                    continue
                raise ValueError(
                    f"unable to resolve host ip for inventory_vm_groups[{group!r}] vm_key={vm_key!r} "
                    f"from inventory_state_ref={inventory_state_ref}"
                )
            host_entry: dict[str, str] = {"name": vm_key, "host": picked}
            host_entry["hyops_resolved_host"] = picked
            host_entry.update(resolve_gcp_instance_contract(outputs, vm_key=vm_key))
            private_host = resolve_vm_private_ipv4(outputs, vm_key=vm_key)
            if private_host:
                host_entry["hyops_private_host"] = private_host
            tags = resolve_vm_tags(outputs, vm_key=vm_key)
            if tags:
                host_entry["tags"] = tags
            hosts.append(host_entry)

        out[group] = hosts

    inputs["inventory_groups"] = out
    current_target_user = str(inputs.get("target_user") or "").strip()
    if not current_target_user or current_target_user == "root":
        inferred_target_user = _infer_inventory_target_user_from_state(state)
        if inferred_target_user:
            inputs["target_user"] = inferred_target_user
    current_ssh_access_mode = str(inputs.get("ssh_access_mode") or "").strip().lower()
    if not current_ssh_access_mode:
        inventory_base_ref, _inventory_instance = split_module_state_ref(inventory_state_ref)
        if inventory_base_ref == "platform/gcp/platform-vm":
            inputs["ssh_access_mode"] = "gcp-iap"


def resolve_hetzner_foundation_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    raw_ref = str(inputs.get("foundation_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        foundation_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.foundation_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and foundation_state_ref in assumed_state_ok:
        if not str(inputs.get("private_network_id") or "").strip():
            inputs["private_network_id"] = "0"
        return

    if state_root is None:
        raise ValueError("inputs.foundation_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, foundation_state_ref)
    except Exception as e:
        raise ValueError(
            f"foundation_state_ref={foundation_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{foundation_state_ref}' or provide inputs.private_network_id explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"foundation_state_ref={foundation_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{foundation_state_ref}' or provide inputs.private_network_id explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    private_network_id = str(outputs.get("private_network_id") or "").strip()
    private_network_cidr = str(outputs.get("private_network_cidr") or "").strip()

    if not str(inputs.get("private_network_id") or "").strip():
        if not private_network_id:
            raise ValueError(
                f"foundation_state_ref={foundation_state_ref} does not publish outputs.private_network_id. "
                "Re-apply the WAN foundation or provide inputs.private_network_id explicitly."
            )
        inputs["private_network_id"] = private_network_id

    if not str(inputs.get("private_network_cidr") or "").strip() and private_network_cidr:
        inputs["private_network_cidr"] = private_network_cidr


def resolve_hetzner_image_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    raw_ref = str(inputs.get("image_state_ref") or "").strip()
    if not raw_ref:
        if str(inputs.get("image") or "").strip():
            return
        return

    try:
        image_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.image_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and image_state_ref in assumed_state_ok:
        inputs["image"] = str(inputs.get("image") or "0").strip() or "0"
        return

    if state_root is None:
        raise ValueError("inputs.image_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, image_state_ref)
    except Exception as e:
        raise ValueError(
            f"image_state_ref={image_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{image_state_ref}' or provide inputs.image explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"image_state_ref={image_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{image_state_ref}' or provide inputs.image explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    image_key = str(inputs.get("image_key") or "").strip()
    images = outputs.get("images")
    if isinstance(images, dict) and image_key:
        record = images.get(image_key)
        if isinstance(record, dict):
            image_ref = str(record.get("image_ref") or "").strip()
            if image_ref:
                # image_state_ref is authoritative when present; do not keep stale
                # saved image ids from earlier reruns.
                inputs["image"] = image_ref
                return

    if image_key and str(outputs.get("image_key") or "").strip() == image_key:
        image_ref = str(outputs.get("image_ref") or "").strip()
        if image_ref:
            inputs["image"] = image_ref
            return

    raise ValueError(
        f"unable to resolve inputs.image from image_state_ref={image_state_ref} "
        f"for image_key={image_key!r}. "
        "Re-apply the VyOS image registration module or provide inputs.image explicitly."
    )


def resolve_vyos_artifact_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve a shared VyOS artifact contract into seed-module inputs."""
    raw_ref = str(inputs.get("artifact_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        artifact_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.artifact_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and artifact_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.artifact_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, artifact_state_ref)
    except Exception as e:
        raise ValueError(
            f"artifact_state_ref={artifact_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{artifact_state_ref}' (recommended: core/shared/vyos-image-build) "
            "or provide inputs.image_source_url explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"artifact_state_ref={artifact_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{artifact_state_ref}' (recommended: core/shared/vyos-image-build) "
            "or provide inputs.image_source_url explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    artifact_key = (
        str(inputs.get("artifact_key") or "").strip()
        or str(inputs.get("image_key") or "").strip()
        or str(inputs.get("template_key") or "").strip()
    )

    record: dict[str, Any] | None = None
    artifacts = outputs.get("artifacts")
    if isinstance(artifacts, dict):
        candidate = artifacts.get(artifact_key) if artifact_key else None
        if isinstance(candidate, dict):
            record = candidate

    if record is None and artifact_key and str(outputs.get("artifact_key") or "").strip() == artifact_key:
        record = outputs

    if record is None:
        available: list[str] = []
        if isinstance(artifacts, dict):
            available = sorted([str(k) for k in artifacts.keys() if str(k)])
        raise ValueError(
            f"unable to resolve VyOS artifact from artifact_state_ref={artifact_state_ref} "
            f"for artifact_key={artifact_key!r}. "
            + (
                f"available artifact keys: {', '.join(available)}"
                if available
                else "state does not publish outputs.artifacts"
            )
        )

    resolved_key = artifact_key or str(record.get("artifact_key") or outputs.get("artifact_key") or "").strip()
    artifact_url = str(record.get("artifact_url") or outputs.get("artifact_url") or "").strip()
    artifact_format = str(record.get("artifact_format") or outputs.get("artifact_format") or "").strip()
    artifact_version = str(record.get("artifact_version") or outputs.get("artifact_version") or "").strip()
    artifact_sha256 = str(record.get("artifact_sha256") or outputs.get("artifact_sha256") or "").strip()
    source_iso_url = str(record.get("source_iso_url") or outputs.get("source_iso_url") or "").strip()

    if not artifact_url:
        raise ValueError(
            f"artifact_state_ref={artifact_state_ref} for artifact_key={resolved_key or artifact_key!r} "
            "does not publish artifact_url. Re-apply core/shared/vyos-image-build (or publish a valid artifact URL) "
            "or provide inputs.image_source_url explicitly."
        )

    # artifact_state_ref is the source of truth for downstream seed/import modules.
    # Override previously persisted derived fields so reruns cannot drift on stale URLs/SHAs.
    if resolved_key:
        inputs["artifact_key"] = resolved_key
    inputs["artifact_url"] = artifact_url
    if artifact_format:
        inputs["artifact_format"] = artifact_format
    if artifact_version:
        inputs["artifact_version"] = artifact_version
    if artifact_sha256:
        inputs["artifact_sha256"] = artifact_sha256
    if source_iso_url:
        inputs["source_iso_url"] = source_iso_url

    inputs["image_source_url"] = artifact_url
    inputs["template_source_url"] = artifact_url
    if artifact_version:
        inputs["image_version"] = artifact_version
        inputs["template_image_version"] = artifact_version
    if "seed_command" in inputs:
        inputs["seed_command"] = ""


def resolve_dns_endpoint_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve DNS record FQDN/targets from an upstream endpoint-publishing module state."""
    raw_ref = str(inputs.get("endpoint_state_ref") or "").strip()
    if not raw_ref:
        return

    endpoint_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="endpoint_state_env",
    )

    try:
        endpoint_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.endpoint_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and endpoint_state_ref in assumed_state_ok:
        return

    if endpoint_state_root is None:
        raise ValueError("inputs.endpoint_state_ref requires runtime state_dir")

    try:
        state = read_module_state(endpoint_state_root, endpoint_state_ref)
    except Exception as e:
        raise ValueError(
            f"endpoint_state_ref={endpoint_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{endpoint_state_ref}' or provide explicit dns inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"endpoint_state_ref={endpoint_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{endpoint_state_ref}' or provide explicit dns inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    fqdn_key = str(inputs.get("endpoint_fqdn_output_key") or "endpoint_dns_name").strip() or "endpoint_dns_name"
    target_key = str(inputs.get("endpoint_target_output_key") or "endpoint_target").strip() or "endpoint_target"

    endpoint_fqdn = str(outputs.get(fqdn_key) or "").strip()
    endpoint_target = pick_ipv4(outputs.get(target_key)) or str(outputs.get(target_key) or "").strip()

    if not str(inputs.get("record_fqdn") or "").strip():
        if endpoint_fqdn:
            inputs["record_fqdn"] = endpoint_fqdn
        else:
            # Optional wiring path: if the upstream module does not publish a DNS
            # name yet, turn the DNS step into a no-op instead of failing the full
            # blueprint.
            inputs["dns_state"] = "absent"
            inputs["required_env"] = []
            return

    if endpoint_target:
        if not isinstance(inputs.get("primary_targets"), list) or not inputs.get("primary_targets"):
            inputs["primary_targets"] = [endpoint_target]
        if not isinstance(inputs.get("secondary_targets"), list) or not inputs.get("secondary_targets"):
            inputs["secondary_targets"] = [endpoint_target]


def resolve_powerdns_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve PowerDNS authority details from upstream state when requested."""
    raw_primary_ref = str(inputs.get("powerdns_primary_state_ref") or "").strip()
    if raw_primary_ref:
        try:
            primary_state_ref = normalize_module_state_ref(raw_primary_ref)
        except Exception:
            raise ValueError(f"inputs.powerdns_primary_state_ref is invalid: {raw_primary_ref!r}")

        if assumed_state_ok is None or primary_state_ref not in assumed_state_ok:
            if state_root is None:
                raise ValueError("inputs.powerdns_primary_state_ref requires runtime state_dir")
            try:
                state = read_module_state(state_root, primary_state_ref)
            except Exception as e:
                raise ValueError(
                    f"powerdns_primary_state_ref={primary_state_ref} state is unavailable: {e}. "
                    f"Re-apply upstream module '{primary_state_ref}' or provide inputs.powerdns_primary_endpoint explicitly."
                ) from e

            status = str(state.get("status") or "").strip().lower()
            if status != "ok":
                raise ValueError(
                    f"powerdns_primary_state_ref={primary_state_ref} is not ready (status={status or 'missing'}). "
                    f"Re-apply upstream module '{primary_state_ref}' or provide inputs.powerdns_primary_endpoint explicitly."
                )

            outputs = state.get("outputs")
            if not isinstance(outputs, dict):
                outputs = {}

            primary_host = str(outputs.get("powerdns_target_host") or "").strip()
            primary_zone = str(outputs.get("powerdns_zone_name") or "").strip()

            if not str(inputs.get("powerdns_primary_endpoint") or "").strip():
                if not primary_host:
                    raise ValueError(
                        f"powerdns_primary_state_ref={primary_state_ref} does not publish outputs.powerdns_target_host. "
                        "Re-apply the shared primary or provide inputs.powerdns_primary_endpoint explicitly."
                    )
                inputs["powerdns_primary_endpoint"] = primary_host

            if not str(inputs.get("powerdns_zone_name") or "").strip() and primary_zone:
                inputs["powerdns_zone_name"] = primary_zone

            if not isinstance(inputs.get("powerdns_allow_notify_from"), list) or not inputs.get("powerdns_allow_notify_from"):
                if primary_host:
                    inputs["powerdns_allow_notify_from"] = [primary_host]

            if not isinstance(inputs.get("powerdns_allow_axfr_ips"), list) or not inputs.get("powerdns_allow_axfr_ips"):
                if primary_host:
                    inputs["powerdns_allow_axfr_ips"] = [primary_host]

    powerdns_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="powerdns_state_env",
    )

    raw_state_ref = str(inputs.get("powerdns_state_ref") or "").strip()
    if not raw_state_ref:
        return

    try:
        powerdns_state_ref = normalize_module_state_ref(raw_state_ref)
    except Exception:
        raise ValueError(f"inputs.powerdns_state_ref is invalid: {raw_state_ref!r}")

    if assumed_state_ok is not None and powerdns_state_ref in assumed_state_ok:
        return

    if powerdns_state_root is None:
        raise ValueError("inputs.powerdns_state_ref requires runtime state_dir")

    try:
        state = read_module_state(powerdns_state_root, powerdns_state_ref)
    except Exception as e:
        raise ValueError(
            f"powerdns_state_ref={powerdns_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{powerdns_state_ref}' or provide explicit PowerDNS API inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"powerdns_state_ref={powerdns_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{powerdns_state_ref}' or provide explicit PowerDNS API inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    api_url = str(outputs.get("powerdns_api_url") or "").strip()
    server_id = str(outputs.get("powerdns_server_id") or "").strip()
    zone_name = str(outputs.get("powerdns_zone_name") or "").strip()
    zone_id = str(outputs.get("powerdns_zone_id") or zone_name).strip()
    api_key_env = str(outputs.get("powerdns_api_key_env") or "").strip()
    control_host = str(outputs.get("powerdns_control_host") or outputs.get("powerdns_public_host") or "").strip()
    control_user = str(outputs.get("powerdns_control_user") or "").strip()

    current_api_url = str(inputs.get("powerdns_api_url") or "").strip()
    if not current_api_url and api_url:
        inputs["powerdns_api_url"] = api_url
        if api_url.startswith("http://"):
            inputs["powerdns_validate_tls"] = False

    if not str(inputs.get("powerdns_server_id") or "").strip() and server_id:
        inputs["powerdns_server_id"] = server_id

    if not str(inputs.get("zone") or "").strip() and zone_name:
        inputs["zone"] = zone_name

    if not str(inputs.get("powerdns_zone_id") or "").strip() and zone_id:
        inputs["powerdns_zone_id"] = zone_id

    if not str(inputs.get("powerdns_api_key_env") or "").strip() and api_key_env:
        inputs["powerdns_api_key_env"] = api_key_env

    provider = str(inputs.get("provider") or "").strip().lower()
    has_inventory_groups = isinstance(inputs.get("inventory_groups"), dict) and bool(inputs.get("inventory_groups"))
    has_inventory_state_ref = bool(str(inputs.get("inventory_state_ref") or "").strip())
    has_target_host = bool(str(inputs.get("target_host") or "").strip())
    if provider == "powerdns-api" and not has_inventory_groups and not has_inventory_state_ref and not has_target_host:
        if control_host:
            control_entry: dict[str, Any] = {
                "name": "powerdns-control",
                "host": control_host,
            }
            if control_user:
                control_entry["ansible_user"] = control_user
            inputs["inventory_groups"] = {"edge_control": [control_entry]}
            target_user = str(inputs.get("target_user") or "").strip()
            if control_user and (not target_user or target_user == "root"):
                inputs["target_user"] = control_user
        else:
            inputs["inventory_groups"] = {
                "edge_control": [
                    {
                        "name": "localhost",
                        "host": "127.0.0.1",
                        "ansible_connection": "local",
                    }
                ]
            }
            inputs["connectivity_check"] = False
            inputs["become"] = False
            dns_state_dir = str(inputs.get("dns_state_dir") or "").strip()
            if not dns_state_dir or dns_state_dir == "/opt/hybridops/dns-routing/state":
                inputs["dns_state_dir"] = "/tmp/hybridops/dns-routing/state"


def resolve_db_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve a standard DB connection contract from another module's state."""
    raw_ref = str(inputs.get("db_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        db_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.db_state_ref is invalid: {raw_ref!r}")

    # Blueprint preflight can "assume" upstream state will exist by execution time.
    if assumed_state_ok is not None and db_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.db_state_ref requires runtime state_dir")

    effective_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="db_state_env",
    )

    try:
        state = read_module_state(effective_state_root, db_state_ref)
    except Exception as e:
        raise ValueError(
            f"db_state_ref={db_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{db_state_ref}' or provide inputs.db_host/db_port/db_name/db_user/db_password_env explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"db_state_ref={db_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{db_state_ref}' or provide inputs.db_host/db_port/db_name/db_user/db_password_env explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    raw_app_key = str(inputs.get("db_app_key") or "netbox").strip() or "netbox"
    if not _INPUT_SEG_RE.fullmatch(raw_app_key):
        raise ValueError(f"inputs.db_app_key is invalid: {raw_app_key!r}")
    db_app_key = raw_app_key

    def pick(field: str) -> Any:
        ok, value = try_get_nested(outputs, f"apps.{db_app_key}.{field}")
        if ok:
            return value
        ok, value = try_get_nested(outputs, field)
        if ok:
            return value
        return None

    resolved: dict[str, Any] = {
        "db_host": pick("db_host"),
        "db_port": pick("db_port"),
        "db_name": pick("db_name"),
        "db_user": pick("db_user"),
        "db_password_env": pick("db_password_env"),
    }

    missing: list[str] = []
    for k in ("db_host", "db_port", "db_name", "db_user", "db_password_env"):
        v = resolved.get(k)
        if v is None:
            missing.append(k)
        elif isinstance(v, str) and not v.strip():
            missing.append(k)

    if missing:
        apps = outputs.get("apps")
        app_keys: list[str] = []
        if isinstance(apps, dict):
            app_keys = sorted([str(k) for k in apps.keys() if str(k)])
        hint = (
            f"expected outputs.apps.<app>.db_* (available apps: {', '.join(app_keys)})"
            if app_keys
            else "expected outputs.apps.<app>.db_* or outputs.db_*"
        )
        raise ValueError(
            f"db_state_ref={db_state_ref} does not publish required DB outputs: {', '.join(missing)} "
            f"({hint}). "
            f"Re-apply upstream module '{db_state_ref}' or provide inputs.db_* explicitly."
        )

    raw_port = resolved.get("db_port")
    if isinstance(raw_port, bool):
        raise ValueError(f"db_state_ref={db_state_ref} output db_port is invalid: {raw_port!r}")
    try:
        db_port = int(raw_port) if isinstance(raw_port, int) else int(str(raw_port).strip())
    except Exception as exc:
        raise ValueError(
            f"db_state_ref={db_state_ref} output db_port is invalid: {raw_port!r}"
        ) from exc
    if db_port < 1 or db_port > 65535:
        raise ValueError(f"db_state_ref={db_state_ref} output db_port is out of range: {db_port}")

    # db_state_ref is authoritative; overwrite any existing values.
    inputs["db_host"] = str(resolved["db_host"]).strip()
    inputs["db_port"] = db_port
    inputs["db_name"] = str(resolved["db_name"]).strip()
    inputs["db_user"] = str(resolved["db_user"]).strip()
    inputs["db_password_env"] = str(resolved["db_password_env"]).strip()


def resolve_prefixed_db_contract_from_state(
    inputs: dict[str, Any],
    *,
    prefix: str,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve a DB contract into prefixed input keys (e.g. source_db_*, target_db_*)."""
    raw_prefix = str(prefix or "").strip()
    if not raw_prefix:
        return
    normalized_prefix = raw_prefix if raw_prefix.endswith("_") else f"{raw_prefix}_"

    key_ref = f"{normalized_prefix}db_state_ref"
    if not str(inputs.get(key_ref) or "").strip():
        return

    shadow: dict[str, Any] = {}
    for key in (
        "db_state_ref",
        "db_state_env",
        "db_app_key",
        "db_host",
        "db_port",
        "db_name",
        "db_user",
        "db_password_env",
    ):
        prefixed_key = f"{normalized_prefix}{key}"
        if prefixed_key in inputs:
            shadow[key] = inputs.get(prefixed_key)
    if "allow_cross_env_state" in inputs:
        shadow["allow_cross_env_state"] = inputs.get("allow_cross_env_state")

    resolve_db_contract_from_state(shadow, state_root=state_root, assumed_state_ok=assumed_state_ok)

    for key in ("db_host", "db_port", "db_name", "db_user", "db_password_env"):
        if key in shadow:
            inputs[f"{normalized_prefix}{key}"] = shadow[key]


def resolve_ssh_keys_from_init(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
) -> None:
    """Resolve inputs.ssh_keys from init readiness metadata when requested."""
    raw_keys = inputs.get("ssh_keys")
    if isinstance(raw_keys, list) and any(str(item or "").strip() for item in raw_keys):
        return

    if not as_bool(inputs.get("ssh_keys_from_init"), default=False):
        return

    if state_root is None:
        raise ValueError("inputs.ssh_keys_from_init=true requires runtime state_dir")

    target = str(inputs.get("ssh_keys_init_target") or "gcp").strip().lower() or "gcp"
    meta_dir = state_root.parent / "meta"

    try:
        marker = read_marker(meta_dir, target)
    except Exception as exc:
        raise ValueError(
            f"inputs.ssh_keys_from_init=true but readiness for init target={target!r} is unavailable: {exc}. "
            f"Run 'hyops init {target} --env <env> --force' or provide inputs.ssh_keys explicitly."
        ) from exc

    status = str(marker.get("status") or "").strip().lower()
    if status != "ready":
        raise ValueError(
            f"inputs.ssh_keys_from_init=true but init target={target!r} is not ready (status={status or 'missing'}). "
            f"Run 'hyops init {target} --env <env> --force' or provide inputs.ssh_keys explicitly."
        )

    context = marker.get("context") if isinstance(marker.get("context"), dict) else {}
    keys: list[str] = []
    raw_list = context.get("ssh_public_keys")
    if isinstance(raw_list, list):
        for item in raw_list:
            token = str(item or "").strip()
            if token:
                keys.append(token)
    raw_single = str(context.get("ssh_public_key") or marker.get("ssh_public_key") or "").strip()
    if raw_single:
        keys.append(raw_single)

    deduped: list[str] = []
    for item in keys:
        if item not in deduped:
            deduped.append(item)

    if not deduped:
        raise ValueError(
            f"inputs.ssh_keys_from_init=true but init target={target!r} does not publish ssh_public_key in readiness metadata. "
            f"Re-run 'hyops init {target} --env <env> --force' with a local public key present or --ssh-public-key, "
            f"or provide inputs.ssh_keys explicitly."
        )

    inputs["ssh_keys"] = deduped


def normalize_repo_backend(raw: Any) -> str:
    backend = str(raw or "").strip().lower()
    if backend in ("gcp",):
        return "gcs"
    if backend in ("azblob", "blob"):
        return "azure"
    if backend in ("s3", "gcs", "azure"):
        return backend
    return ""


def resolve_project_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve inputs.project_id from upstream module state when requested."""
    raw_ref = str(inputs.get("project_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        project_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.project_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and project_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.project_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, project_state_ref)
    except Exception as e:
        raise ValueError(
            f"project_state_ref={project_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{project_state_ref}' or provide inputs.project_id explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"project_state_ref={project_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{project_state_ref}' or provide inputs.project_id explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    project_id = str(outputs.get("project_id") or "").strip()
    if not project_id:
        raise ValueError(
            f"project_state_ref={project_state_ref} does not publish required output project_id."
        )

    inputs["project_id"] = project_id


def resolve_gcp_project_factory_contract_from_init(
    inputs: dict[str, Any],
    *,
    runtime_root: Path | None,
) -> None:
    """Resolve org/gcp/project-factory billing input from env-scoped GCP init config."""
    if runtime_root is None:
        return
    if str(inputs.get("billing_account") or "").strip() or str(inputs.get("billing_account_id") or "").strip():
        return

    config_path = runtime_root / "config" / "gcp.conf"
    if config_path.exists():
        try:
            cfg = read_kv_file(config_path)
        except Exception:
            cfg = {}
        billing_account_id = normalize_billing_account_id(str(cfg.get("GCP_BILLING_ACCOUNT_ID") or "").strip())
        if billing_account_id:
            inputs["billing_account_id"] = billing_account_id
            return

    ready_path = runtime_root / "meta"
    try:
        marker = read_marker(ready_path, "gcp")
    except Exception:
        return
    context = marker.get("context")
    if not isinstance(context, dict):
        return
    billing_account_id = normalize_billing_account_id(str(context.get("billing_account_id") or "").strip())
    if billing_account_id:
        inputs["billing_account_id"] = billing_account_id


def resolve_kubeconfig_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve inputs.kubeconfig_path from upstream module state when requested."""
    raw_ref = str(inputs.get("kubeconfig_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        kubeconfig_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.kubeconfig_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and kubeconfig_state_ref in assumed_state_ok:
        inputs.setdefault(
            "kubeconfig_path",
            str(inputs.get("kubeconfig_path") or "/tmp/hyops-placeholder-kubeconfig.yaml"),
        )
        return

    if state_root is None:
        raise ValueError("inputs.kubeconfig_state_ref requires runtime state_dir")

    effective_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="kubeconfig_state_env",
    )

    try:
        state = read_module_state(effective_state_root, kubeconfig_state_ref)
    except Exception as e:
        raise ValueError(
            f"kubeconfig_state_ref={kubeconfig_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{kubeconfig_state_ref}' or provide inputs.kubeconfig_path explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"kubeconfig_state_ref={kubeconfig_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{kubeconfig_state_ref}' or provide inputs.kubeconfig_path explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    kubeconfig_path = str(outputs.get("kubeconfig_path") or "").strip()
    if not kubeconfig_path:
        raise ValueError(
            f"kubeconfig_state_ref={kubeconfig_state_ref} does not publish required output kubeconfig_path."
        )
    inputs["kubeconfig_path"] = kubeconfig_path


def resolve_gke_cluster_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve GKE cluster coordinates from upstream cluster state when requested."""
    raw_ref = str(inputs.get("cluster_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        cluster_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.cluster_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and cluster_state_ref in assumed_state_ok:
        inputs.setdefault("project_id", str(inputs.get("project_id") or "placeholder-project"))
        inputs.setdefault("location", str(inputs.get("location") or "europe-west2-b"))
        inputs.setdefault("cluster_name", str(inputs.get("cluster_name") or "placeholder-cluster"))
        return

    if state_root is None:
        raise ValueError("inputs.cluster_state_ref requires runtime state_dir")

    effective_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="cluster_state_env",
    )

    try:
        state = read_module_state(effective_state_root, cluster_state_ref)
    except Exception as e:
        raise ValueError(
            f"cluster_state_ref={cluster_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{cluster_state_ref}' or provide explicit GKE cluster inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"cluster_state_ref={cluster_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{cluster_state_ref}' or provide explicit GKE cluster inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    project_id = str(outputs.get("project_id") or "").strip()
    location = str(outputs.get("location") or "").strip()
    cluster_name = str(outputs.get("cluster_name") or "").strip()
    if not project_id or not location or not cluster_name:
        raise ValueError(
            f"cluster_state_ref={cluster_state_ref} does not publish required outputs project_id, location, and cluster_name."
        )

    inputs["project_id"] = project_id
    inputs["location"] = location
    inputs["cluster_name"] = cluster_name


def resolve_network_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve GCP-style network coordinates from upstream module state when requested."""
    raw_ref = str(inputs.get("network_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        network_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.network_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and network_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.network_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, network_state_ref)
    except Exception as e:
        raise ValueError(
            f"network_state_ref={network_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{network_state_ref}' or provide inputs.private_network explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"network_state_ref={network_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{network_state_ref}' or provide inputs.private_network explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    network_ref = str(
        outputs.get("network_self_link")
        or outputs.get("private_network")
        or outputs.get("network_name")
        or ""
    ).strip()
    if not network_ref:
        raise ValueError(
            f"network_state_ref={network_state_ref} does not publish required output network_self_link or network_name."
        )

    if "private_network" in inputs:
        inputs["private_network"] = network_ref

    if "network" in inputs:
        # Prefer the self-link to avoid ambiguity in Shared VPC / cross-project cases.
        inputs["network"] = network_ref

    if "subnetwork" in inputs:
        subnetwork_output_key = str(inputs.get("subnetwork_output_key") or "").strip()
        if subnetwork_output_key:
            subnetwork_self_link_key = (
                f"{subnetwork_output_key[:-5]}_self_link"
                if subnetwork_output_key.endswith("_name")
                else f"{subnetwork_output_key}_self_link"
            )
            subnetwork_value = str(
                outputs.get(subnetwork_self_link_key)
                or outputs.get(subnetwork_output_key)
                or ""
            ).strip()
            if not subnetwork_value:
                available = sorted(str(k) for k in outputs.keys() if str(k))
                raise ValueError(
                    f"network_state_ref={network_state_ref} does not publish subnetwork output "
                    f"{subnetwork_output_key!r}. "
                    + (
                        f"available outputs: {', '.join(available)}"
                        if available
                        else "state does not publish any outputs"
                    )
                )
            inputs["subnetwork"] = subnetwork_value

    if "subnetwork_self_links" in inputs:
        raw_output_keys = inputs.get("subnetwork_output_keys")
        if isinstance(raw_output_keys, list) and raw_output_keys:
            resolved_self_links: list[str] = []
            for idx, raw_key in enumerate(raw_output_keys, start=1):
                output_key = str(raw_key or "").strip()
                if not output_key:
                    raise ValueError(f"inputs.subnetwork_output_keys[{idx}] must be a non-empty string")
                subnetwork_self_link_key = (
                    f"{output_key[:-5]}_self_link"
                    if output_key.endswith("_name")
                    else f"{output_key}_self_link"
                )
                subnetwork_value = str(
                    outputs.get(subnetwork_self_link_key)
                    or outputs.get(output_key)
                    or ""
                ).strip()
                if not subnetwork_value:
                    available = sorted(str(k) for k in outputs.keys() if str(k))
                    raise ValueError(
                        f"network_state_ref={network_state_ref} does not publish subnetwork output "
                        f"{output_key!r}. "
                        + (
                            f"available outputs: {', '.join(available)}"
                            if available
                            else "state does not publish any outputs"
                        )
                    )
                resolved_self_links.append(subnetwork_value)
            inputs["subnetwork_self_links"] = resolved_self_links

    if "pods_secondary_range_name" in inputs:
        output_key = str(inputs.get("pods_secondary_range_output_key") or "").strip()
        if output_key:
            value = str(outputs.get(output_key) or "").strip()
            if not value:
                available = sorted(str(k) for k in outputs.keys() if str(k))
                raise ValueError(
                    f"network_state_ref={network_state_ref} does not publish secondary range output "
                    f"{output_key!r}. "
                    + (
                        f"available outputs: {', '.join(available)}"
                        if available
                        else "state does not publish any outputs"
                    )
                )
            inputs["pods_secondary_range_name"] = value

    if "services_secondary_range_name" in inputs:
        output_key = str(inputs.get("services_secondary_range_output_key") or "").strip()
        if output_key:
            value = str(outputs.get(output_key) or "").strip()
            if not value:
                available = sorted(str(k) for k in outputs.keys() if str(k))
                raise ValueError(
                    f"network_state_ref={network_state_ref} does not publish secondary range output "
                    f"{output_key!r}. "
                    + (
                        f"available outputs: {', '.join(available)}"
                        if available
                        else "state does not publish any outputs"
                    )
                )
            inputs["services_secondary_range_name"] = value

    project_id = str(outputs.get("project_id") or "").strip()
    if project_id and not str(inputs.get("network_project_id") or "").strip():
        inputs["network_project_id"] = project_id
    if project_id and not str(inputs.get("project_id") or "").strip():
        inputs["project_id"] = project_id

    region = str(outputs.get("region") or "").strip()
    if region and not str(inputs.get("region") or "").strip():
        inputs["region"] = region

    if "network_self_link" in inputs and not str(inputs.get("network_self_link") or "").strip():
        inputs["network_self_link"] = network_ref


def resolve_router_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve GCP Cloud Router coordinates from upstream module state when requested."""
    raw_ref = str(inputs.get("router_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        router_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.router_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and router_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.router_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, router_state_ref)
    except Exception as e:
        raise ValueError(
            f"router_state_ref={router_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{router_state_ref}' or provide inputs.router_name explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"router_state_ref={router_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{router_state_ref}' or provide inputs.router_name explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    router_name = str(outputs.get("router_name") or "").strip()
    if not router_name:
        raise ValueError(
            f"router_state_ref={router_state_ref} does not publish required output router_name."
        )

    inputs["router_name"] = router_name

    project_id = str(outputs.get("project_id") or "").strip()
    if project_id and not str(inputs.get("project_id") or "").strip():
        inputs["project_id"] = project_id

    region = str(outputs.get("region") or "").strip()
    if region and not str(inputs.get("region") or "").strip():
        inputs["region"] = region

    network_self_link = str(outputs.get("network_self_link") or "").strip()
    if network_self_link and "network_self_link" in inputs and not str(inputs.get("network_self_link") or "").strip():
        inputs["network_self_link"] = network_self_link


def resolve_repo_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve backup repository settings from another module's state."""
    raw_ref = str(inputs.get("repo_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        repo_state_ref = normalize_module_state_ref(raw_ref)
        repo_ref_base, repo_instance = split_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.repo_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and repo_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.repo_state_ref requires runtime state_dir")

    ready_instances = _ready_repo_state_instances(state_root, repo_state_ref)
    if repo_instance is None and len(ready_instances) > 1:
        choices = ", ".join(f"{repo_ref_base}#{name}" for name in ready_instances)
        raise ValueError(
            f"inputs.repo_state_ref={repo_ref_base} is ambiguous: multiple ready repository state instances exist "
            f"({choices}). Use an explicit state instance."
        )

    try:
        state = read_module_state(state_root, repo_state_ref)
    except Exception as e:
        raise ValueError(
            f"repo_state_ref={repo_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{repo_state_ref}' or provide backend-specific repo inputs explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"repo_state_ref={repo_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{repo_state_ref}' or provide backend-specific repo inputs explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    backend = normalize_repo_backend(outputs.get("repo_backend"))
    if not backend:
        backend = normalize_repo_backend(outputs.get("repo_provider"))
    if backend not in ("s3", "gcs", "azure"):
        raise ValueError(
            f"repo_state_ref={repo_state_ref} does not publish a valid repository backend "
            f"(expected outputs.repo_backend in s3|gcs|azure)."
        )

    if backend == "s3":
        bucket = str(outputs.get("repo_bucket_name") or outputs.get("bucket_name") or "").strip()
        if not bucket:
            raise ValueError(
                f"repo_state_ref={repo_state_ref} does not publish required output repo_bucket_name for backend=s3"
            )
        inputs["backend"] = "s3"
        inputs["s3_bucket"] = bucket
        return

    if backend == "gcs":
        bucket = str(outputs.get("repo_bucket_name") or outputs.get("bucket_name") or "").strip()
        if not bucket:
            raise ValueError(
                f"repo_state_ref={repo_state_ref} does not publish required output repo_bucket_name for backend=gcs"
            )
        inputs["backend"] = "gcs"
        inputs["gcs_bucket"] = bucket
        return

    container = str(outputs.get("container_name") or outputs.get("repo_bucket_name") or "").strip()
    account = str(outputs.get("storage_account_name") or outputs.get("repo_principal_name") or "").strip()
    if not container or not account:
        raise ValueError(
            f"repo_state_ref={repo_state_ref} does not publish required outputs for backend=azure "
            f"(expected container_name/repo_bucket_name and storage_account_name/repo_principal_name)."
        )
    inputs["backend"] = "azure"
    inputs["azure_container"] = container
    inputs["azure_storage_account"] = account


def resolve_prefixed_repo_contract_from_state(
    inputs: dict[str, Any],
    *,
    prefix: str,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve prefixed repository settings from module state.

    Example for prefix='secondary':
      - inputs.secondary_repo_state_ref -> resolved into
        inputs.secondary_backend / inputs.secondary_* repository fields.
    """
    token = str(prefix or "").strip()
    if not token:
        return
    if not _INPUT_SEG_RE.fullmatch(token):
        raise ValueError(f"invalid repo contract prefix: {prefix!r}")

    normalized_prefix = f"{token}_"
    raw_ref = str(inputs.get(f"{normalized_prefix}repo_state_ref") or "").strip()
    if not raw_ref:
        return

    shadow: dict[str, Any] = {}
    for key in (
        "repo_state_ref",
        "backend",
        "s3_bucket",
        "s3_endpoint",
        "s3_region",
        "s3_uri_style",
        "s3_access_key_env",
        "s3_secret_key_env",
        "gcs_bucket",
        "gcs_sa_json_env",
        "gcs_sa_dest",
        "azure_storage_account",
        "azure_container",
        "azure_account_key_env",
    ):
        prefixed_key = f"{normalized_prefix}{key}"
        if prefixed_key in inputs:
            shadow[key] = inputs.get(prefixed_key)

    resolve_repo_contract_from_state(shadow, state_root=state_root, assumed_state_ok=assumed_state_ok)

    for key in (
        "backend",
        "s3_bucket",
        "s3_endpoint",
        "s3_region",
        "s3_uri_style",
        "gcs_bucket",
        "azure_storage_account",
        "azure_container",
    ):
        if key in shadow:
            inputs[f"{normalized_prefix}{key}"] = shadow[key]


def resolve_postgresql_backup_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve pgBackRest restore selectors from a PostgreSQL backup module state."""
    raw_ref = str(inputs.get("backup_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        backup_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.backup_state_ref is invalid: {raw_ref!r}")

    backup_base_ref, _backup_instance = split_module_state_ref(backup_state_ref)
    if backup_base_ref not in _PGHA_BACKUP_STATE_REFS:
        raise ValueError(
            "inputs.backup_state_ref currently requires "
            "platform/postgresql-ha-backup or platform/onprem/postgresql-ha-backup"
        )

    if assumed_state_ok is not None and backup_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.backup_state_ref requires runtime state_dir")

    effective_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="backup_state_env",
    )

    try:
        state = read_module_state(effective_state_root, backup_state_ref)
    except Exception as e:
        raise ValueError(
            f"backup_state_ref={backup_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream backup module '{backup_state_ref}' or provide "
            f"inputs.restore_set explicitly."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"backup_state_ref={backup_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream backup module '{backup_state_ref}' or provide "
            f"inputs.restore_set explicitly."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    raw_latest = outputs.get("pgbackrest_latest_backup")
    latest = raw_latest if isinstance(raw_latest, dict) else {}
    available = bool(latest.get("available"))
    backup_set = str(
        outputs.get("pgbackrest_latest_backup_set")
        or latest.get("label")
        or ""
    ).strip()
    if not available and not backup_set:
        raise ValueError(
            f"backup_state_ref={backup_state_ref} does not publish an available pgBackRest backup. "
            f"Expected outputs.pgbackrest_latest_backup_set and pgbackrest_latest_backup.available=true."
        )

    if not backup_set:
        raise ValueError(
            f"backup_state_ref={backup_state_ref} does not publish required output pgbackrest_latest_backup_set."
        )
    if not str(inputs.get("restore_set") or "").strip():
        inputs["restore_set"] = backup_set


def resolve_postgresql_dr_source_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve PostgreSQL DR source assessment outputs from upstream state."""
    apply_mode = str(inputs.get("apply_mode") or "").strip().lower()
    if apply_mode == "status" and str(inputs.get("replica_state_ref") or "").strip():
        return

    raw_ref = str(inputs.get("source_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        source_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.source_state_ref is invalid: {raw_ref!r}")

    source_base_ref, _source_instance = split_module_state_ref(source_state_ref)
    if source_base_ref != "platform/onprem/postgresql-dr-source":
        raise ValueError(
            "inputs.source_state_ref currently requires platform/onprem/postgresql-dr-source"
        )

    if assumed_state_ok is not None and source_state_ref in assumed_state_ok:
        inputs.setdefault(
            "source_contract",
            {
                "contract_version": int(inputs.get("source_contract_version") or 1),
                "provider": "onprem",
                "engine": "postgresql",
            },
        )
        inputs.setdefault("source_host", "0.0.0.0")
        inputs.setdefault("source_port", 5432)
        return

    if state_root is None:
        raise ValueError("inputs.source_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, source_state_ref)
    except Exception as e:
        raise ValueError(
            f"source_state_ref={source_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{source_state_ref}' or provide explicit source contract inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"source_state_ref={source_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{source_state_ref}' or provide explicit source contract inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    source_contract = outputs.get("source")
    if not isinstance(source_contract, dict) or not source_contract:
        raise ValueError(
            f"source_state_ref={source_state_ref} does not publish required output source."
        )

    inputs["source_contract"] = source_contract

    source_host = str(outputs.get("source_host") or source_contract.get("db_host") or "").strip()
    if source_host:
        inputs["source_host"] = source_host

    source_port = outputs.get("source_port", source_contract.get("db_port"))
    if isinstance(source_port, int):
        inputs["source_port"] = source_port

    source_db_name = str(outputs.get("db_name") or source_contract.get("db_name") or "").strip()
    if source_db_name:
        inputs["source_db_name"] = source_db_name

    source_db_user = str(outputs.get("db_user") or source_contract.get("db_user") or "").strip()
    if source_db_user:
        inputs["source_db_user"] = source_db_user

    source_leader_name = str(outputs.get("source_leader_name") or source_contract.get("leader_name") or "").strip()
    if source_leader_name:
        inputs["source_leader_name"] = source_leader_name

    source_leader_host = str(outputs.get("source_leader_host") or source_contract.get("leader_host") or "").strip()
    if source_leader_host:
        inputs["source_leader_host"] = source_leader_host

    inputs["source_export_ready"] = bool(
        outputs.get("source_export_ready", source_contract.get("export_ready"))
    )
    inputs["source_replication_candidate"] = bool(
        outputs.get("source_replication_candidate", source_contract.get("replication_candidate"))
    )


def resolve_cloudsql_external_replica_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve Cloud SQL external replica status inputs from prior module state."""
    raw_ref = str(inputs.get("replica_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        replica_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.replica_state_ref is invalid: {raw_ref!r}")

    replica_base_ref, _replica_instance = split_module_state_ref(replica_state_ref)
    if replica_base_ref != "org/gcp/cloudsql-external-replica":
        raise ValueError(
            "inputs.replica_state_ref currently requires org/gcp/cloudsql-external-replica"
        )

    if assumed_state_ok is not None and replica_state_ref in assumed_state_ok:
        if not str(inputs.get("project_id") or "").strip():
            inputs["project_id"] = "placeholder-project"
        if not str(inputs.get("region") or "").strip():
            inputs["region"] = "europe-west2"
        if not str(inputs.get("source_connection_profile_name") or "").strip():
            inputs["source_connection_profile_name"] = "placeholder-source"
        if not str(inputs.get("destination_connection_profile_name") or "").strip():
            inputs["destination_connection_profile_name"] = "placeholder-destination"
        if not str(inputs.get("migration_job_name") or "").strip():
            inputs["migration_job_name"] = "placeholder-job"
        return

    if state_root is None:
        raise ValueError("inputs.replica_state_ref requires runtime state_dir")

    effective_state_root = resolve_state_root_for_env_override(
        inputs,
        state_root=state_root,
        override_key="replica_state_env",
    )

    try:
        state = read_module_state(effective_state_root, replica_state_ref)
    except Exception as e:
        raise ValueError(
            f"replica_state_ref={replica_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{replica_state_ref}' or provide explicit managed standby status inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"replica_state_ref={replica_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{replica_state_ref}' or provide explicit managed standby status inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    resolved_inputs = _load_resolved_inputs_from_state(state, state_root=effective_state_root)
    rerun_inputs = _load_rerun_inputs_from_state(state)
    for key in (
        "project_state_ref",
        "project_id",
        "network_state_ref",
        "network_project_id",
        "private_network",
        "region",
        "connectivity_mode",
        "reverse_ssh_state_ref",
        "reverse_ssh_vm",
        "reverse_ssh_vm_ip",
        "reverse_ssh_vm_zone",
        "reverse_ssh_vm_port",
        "reverse_ssh_vpc",
        "source_state_ref",
        "source_contract",
        "source_host",
        "source_port",
        "source_db_name",
        "source_db_user",
        "source_leader_name",
        "source_leader_host",
        "source_export_ready",
        "source_replication_candidate",
        "source_replication_user",
        "source_replication_password_env",
        "source_ssl_type",
        "source_ca_certificate_env",
        "source_client_certificate_env",
        "source_private_key_env",
        "source_connection_profile_name",
        "destination_connection_profile_name",
        "migration_job_name",
        "migration_job_type",
        "required_env",
        "gcloud_bin",
        "gcloud_copy_default_config",
        "gcloud_runtime_config_dir",
        "gcloud_active_account",
        "endpoint_dns_name",
    ):
        _backfill_input_from_mapping(inputs, resolved_inputs, key)
        _backfill_input_from_mapping(inputs, rerun_inputs, key)

    project_id = str(outputs.get("target_project_id") or "").strip()
    if project_id:
        inputs["project_id"] = project_id

    region = str(outputs.get("target_region") or "").strip()
    if region:
        inputs["region"] = region

    source_host = str(outputs.get("source_host") or "").strip()
    if source_host:
        inputs["source_host"] = source_host

    source_port = outputs.get("source_port")
    if isinstance(source_port, int):
        inputs["source_port"] = source_port

    source_leader_name = str(outputs.get("source_leader_name") or "").strip()
    if source_leader_name:
        inputs["source_leader_name"] = source_leader_name

    source_replication_candidate = outputs.get("source_replication_candidate")
    if isinstance(source_replication_candidate, bool):
        inputs["source_replication_candidate"] = source_replication_candidate

    connectivity_mode = str(outputs.get("connectivity_mode") or "").strip()
    if connectivity_mode:
        inputs["connectivity_mode"] = connectivity_mode

    source_connection_profile_name = str(outputs.get("source_connection_profile_name") or "").strip()
    if source_connection_profile_name:
        inputs["source_connection_profile_name"] = source_connection_profile_name

    destination_connection_profile_name = str(outputs.get("destination_connection_profile_name") or "").strip()
    if destination_connection_profile_name:
        inputs["destination_connection_profile_name"] = destination_connection_profile_name

    migration_job_name = str(outputs.get("migration_job_name") or "").strip()
    if migration_job_name:
        inputs["migration_job_name"] = migration_job_name

    target_instance_name = str(outputs.get("target_instance_name") or "").strip()
    if target_instance_name:
        inputs["target_instance_name"] = target_instance_name

    target_db_host = str(outputs.get("target_db_host") or outputs.get("endpoint_host") or "").strip()
    if target_db_host:
        inputs["target_db_host"] = target_db_host

    target_connection_name = str(outputs.get("target_connection_name") or "").strip()
    if target_connection_name:
        inputs["target_connection_name"] = target_connection_name

    endpoint_dns_name = str(outputs.get("endpoint_dns_name") or "").strip()
    if endpoint_dns_name:
        inputs["endpoint_dns_name"] = endpoint_dns_name


def resolve_cloudsql_target_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve Cloud SQL target contract from upstream state."""
    apply_mode = str(inputs.get("apply_mode") or "assess").strip().lower()
    if apply_mode in {"establish", "status"}:
        # DMS establish/status creates or inspects its own Cloud SQL destination.
        # The standalone Cloud SQL module is only part of the assess contract.
        return

    raw_ref = str(inputs.get("managed_target_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        target_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.managed_target_state_ref is invalid: {raw_ref!r}")

    target_base_ref, _target_instance = split_module_state_ref(target_state_ref)
    if target_base_ref != "org/gcp/cloudsql-postgresql":
        raise ValueError(
            "inputs.managed_target_state_ref currently requires org/gcp/cloudsql-postgresql"
        )

    if assumed_state_ok is not None and target_state_ref in assumed_state_ok:
        inputs.setdefault("target_project_id", str(inputs.get("target_project_id") or "placeholder-project"))
        inputs.setdefault("target_region", str(inputs.get("target_region") or "europe-west2"))
        inputs.setdefault("target_instance_name", str(inputs.get("target_instance_name") or "placeholder-instance"))
        return

    if state_root is None:
        raise ValueError("inputs.managed_target_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, target_state_ref)
    except Exception as e:
        raise ValueError(
            f"managed_target_state_ref={target_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{target_state_ref}' or provide explicit target inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"managed_target_state_ref={target_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{target_state_ref}' or provide explicit target inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    target_project_id = str(outputs.get("project_id") or "").strip()
    target_region = str(outputs.get("region") or "").strip()
    target_instance_name = str(outputs.get("instance_name") or "").strip()
    if not target_project_id or not target_region or not target_instance_name:
        raise ValueError(
            f"managed_target_state_ref={target_state_ref} does not publish required outputs project_id, region, and instance_name."
        )

    inputs["target_project_id"] = target_project_id
    inputs["target_region"] = target_region
    inputs["target_instance_name"] = target_instance_name

    target_db_host = str(outputs.get("db_host") or outputs.get("private_ip_address") or "").strip()
    if target_db_host:
        inputs["target_db_host"] = target_db_host

    target_connection_name = str(outputs.get("connection_name") or "").strip()
    if target_connection_name:
        inputs["target_connection_name"] = target_connection_name


def resolve_reverse_ssh_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve reverse SSH bastion coordinates from upstream VM state."""
    if str(inputs.get("connectivity_mode") or "").strip().lower() != "reverse-ssh":
        return

    raw_ref = str(inputs.get("reverse_ssh_state_ref") or "").strip()
    if not raw_ref:
        return

    try:
        bastion_state_ref = normalize_module_state_ref(raw_ref)
    except Exception:
        raise ValueError(f"inputs.reverse_ssh_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and bastion_state_ref in assumed_state_ok:
        inputs.setdefault("reverse_ssh_vm", str(inputs.get("reverse_ssh_vm") or "placeholder-vm"))
        inputs.setdefault("reverse_ssh_vm_ip", str(inputs.get("reverse_ssh_vm_ip") or "10.0.0.2"))
        inputs.setdefault("reverse_ssh_vm_zone", str(inputs.get("reverse_ssh_vm_zone") or "europe-west2-a"))
        if not int(inputs.get("reverse_ssh_vm_port") or 0):
            inputs["reverse_ssh_vm_port"] = 15432
        return

    if state_root is None:
        raise ValueError("inputs.reverse_ssh_state_ref requires runtime state_dir")

    try:
        state = read_module_state(state_root, bastion_state_ref)
    except Exception as e:
        raise ValueError(
            f"reverse_ssh_state_ref={bastion_state_ref} state is unavailable: {e}. "
            f"Re-apply upstream module '{bastion_state_ref}' or provide explicit reverse SSH inputs."
        ) from e

    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(
            f"reverse_ssh_state_ref={bastion_state_ref} is not ready (status={status or 'missing'}). "
            f"Re-apply upstream module '{bastion_state_ref}' or provide explicit reverse SSH inputs."
        )

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    vms = outputs.get("vms")
    if not isinstance(vms, dict) or not vms:
        raise ValueError(
            f"reverse_ssh_state_ref={bastion_state_ref} does not publish outputs.vms. "
            "Provide explicit reverse SSH inputs or re-apply the upstream VM module."
        )

    selected: dict[str, Any] | None = None
    reverse_ssh_vm = str(inputs.get("reverse_ssh_vm") or "").strip()
    if reverse_ssh_vm:
        for vm_key, vm_data in vms.items():
            if not isinstance(vm_data, dict):
                continue
            vm_name = str(vm_data.get("vm_name") or "").strip()
            if reverse_ssh_vm in {str(vm_key).strip(), vm_name}:
                selected = vm_data
                if not vm_name:
                    selected = dict(vm_data)
                    selected["vm_name"] = reverse_ssh_vm
                break
        if selected is None:
            raise ValueError(
                f"reverse_ssh_state_ref={bastion_state_ref} does not contain reverse_ssh_vm={reverse_ssh_vm!r}."
            )
    else:
        if len(vms) != 1:
            raise ValueError(
                f"reverse_ssh_state_ref={bastion_state_ref} publishes multiple VMs. "
                "Set inputs.reverse_ssh_vm to select the bastion explicitly."
            )
        _vm_key, vm_data = next(iter(vms.items()))
        if not isinstance(vm_data, dict):
            raise ValueError(
                f"reverse_ssh_state_ref={bastion_state_ref} publishes an invalid outputs.vms entry."
            )
        selected = vm_data

    selected_name = str(selected.get("vm_name") or "").strip()
    selected_ip = str(
        selected.get("ipv4_configured_primary")
        or selected.get("ipv4_address")
        or ""
    ).strip()
    selected_zone = str(selected.get("zone") or "").strip()

    if not selected_name or not selected_ip:
        raise ValueError(
            f"reverse_ssh_state_ref={bastion_state_ref} does not publish a usable VM name and IPv4 address."
        )

    if not str(inputs.get("reverse_ssh_vm") or "").strip():
        inputs["reverse_ssh_vm"] = selected_name
    if not str(inputs.get("reverse_ssh_vm_ip") or "").strip():
        inputs["reverse_ssh_vm_ip"] = selected_ip
    if selected_zone and not str(inputs.get("reverse_ssh_vm_zone") or "").strip():
        inputs["reverse_ssh_vm_zone"] = selected_zone
    if not int(inputs.get("reverse_ssh_vm_port") or 0):
        inputs["reverse_ssh_vm_port"] = 15432
