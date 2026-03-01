"""Runtime state contract resolution helpers.

purpose: Resolve target/inventory/database/repository contracts from upstream module state.
Architecture Decision: ADR-N/A (module resolution)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import ipaddress
import re

from hyops.runtime.coerce import as_bool
from hyops.runtime.readiness import read_marker
from hyops.runtime.module_inputs import try_get_nested
from hyops.runtime.module_state import (
    normalize_module_state_ref,
    read_module_state,
    split_module_state_ref,
)


_INPUT_SEG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_GCP_VM_ID_RE = re.compile(r"^projects/(?P<project>[^/]+)/zones/(?P<zone>[^/]+)/instances/(?P<name>[^/]+)$")


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
        if inventory_base_ref not in ("platform/onprem/platform-vm", "platform/onprem/postgresql-ha"):
            raise ValueError(
                "inputs.inventory_requires_ipam=true currently requires "
                "inputs.inventory_state_ref=platform/onprem/platform-vm or platform/onprem/postgresql-ha"
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
            if inventory_base_ref == "platform/onprem/postgresql-ha":
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
                        "inventory_state_ref=platform/onprem/postgresql-ha does not prove NetBox-IPAM provenance. "
                        "Expected state.input_contract.inventory_state_ref=platform/onprem/platform-vm[#instance] and "
                        "state.input_contract.inventory_requires_ipam=true."
                    )
            elif inventory_base_ref != "platform/onprem/platform-vm":
                raise ValueError(
                    "inputs.inventory_requires_ipam=true requires inventory state published either directly from "
                    "platform/onprem/platform-vm or transitively from platform/onprem/postgresql-ha."
                )

        inputs["inventory_groups"] = published_inventory_groups
        return

    if not isinstance(raw_groups, dict) or not raw_groups:
        inventory_base_ref, _inventory_instance = split_module_state_ref(inventory_state_ref)
        if inventory_base_ref == "platform/onprem/postgresql-ha":
            raise ValueError(
                "inventory_state_ref=platform/onprem/postgresql-ha does not yet publish outputs.inventory_groups. "
                "Re-apply upstream module 'platform/onprem/postgresql-ha' once to refresh its state contract, "
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
            host_entry.update(resolve_gcp_instance_contract(outputs, vm_key=vm_key))
            tags = resolve_vm_tags(outputs, vm_key=vm_key)
            if tags:
                host_entry["tags"] = tags
            hosts.append(host_entry)

        out[group] = hosts

    inputs["inventory_groups"] = out


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

    db_state_env = str(inputs.get("db_state_env") or "").strip()
    effective_state_root = state_root
    if db_state_env:
        try:
            runtime_root = state_root.parent
            envs_root = runtime_root.parent
            candidate = (envs_root / db_state_env / "state").resolve()
            if candidate.exists():
                effective_state_root = candidate
            else:
                raise ValueError(
                    f"inputs.db_state_env={db_state_env!r} resolved state dir does not exist: {candidate}"
                )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"inputs.db_state_env is invalid: {db_state_env!r}") from exc

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
    except Exception:
        raise ValueError(f"inputs.repo_state_ref is invalid: {raw_ref!r}")

    if assumed_state_ok is not None and repo_state_ref in assumed_state_ok:
        return

    if state_root is None:
        raise ValueError("inputs.repo_state_ref requires runtime state_dir")

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


def resolve_postgresql_dr_source_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve PostgreSQL DR source assessment outputs from upstream state."""
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


def resolve_cloudsql_target_contract_from_state(
    inputs: dict[str, Any],
    *,
    state_root: Path | None,
    assumed_state_ok: set[str] | None = None,
) -> None:
    """Resolve Cloud SQL target contract from upstream state."""
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
