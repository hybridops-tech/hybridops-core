"""Role smoke test commands.

purpose: Run collection role smoke playbooks through a first-class HybridOps workflow.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hyops.drivers.config.ansible.driver import _resolve_hyops_executable
from hyops.drivers.config.ansible.execution import build_playbook_argv
from hyops.drivers.config.ansible.inventory import write_inventory
from hyops.drivers.config.ansible.process import run_capture_with_policy
from hyops.drivers.config.ansible.runtime_env import (
    configure_ansible_search_paths,
    ensure_hybridops_collections_available,
    materialize_ssh_private_key_from_env,
    merge_vault_env,
    missing_env,
    prepare_ansible_controller_env,
    resolve_ansible_controller_python,
)
from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id
from hyops.runtime.exitcodes import DEPENDENCY_MISSING, OK, OPERATOR_ERROR, REMOTE_FAILED, SECRETS_FAILED
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_state_contracts import resolve_inventory_groups_from_state
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.source_roots import discover_collections_workspace


_WORKSPACE_COLLECTION_RE = re.compile(r"^ansible-collection-([a-z0-9_.-]+)$")
_ROLE_REF_RE = re.compile(r"^[a-z0-9_.-]+$")
_INVENTORY_FILE_NAMES = {
    "hosts.ini",
    "inventory.ini",
    "hosts.yml",
    "hosts.yaml",
    "inventory.yml",
    "inventory.yaml",
    "inventory.sample.ini",
    "inventory.sample.yml",
    "inventory.sample.yaml",
    "inventory.example.ini",
    "inventory.example.yml",
    "inventory.example.yaml",
}
_DEFAULT_MANIFEST = "hyops.role-test.yml"


@dataclass(frozen=True)
class RoleTarget:
    collection: str
    role: str
    fqcn: str
    collection_root: Path
    role_dir: Path


@dataclass(frozen=True)
class RoleSmokeManifest:
    path: Path | None
    payload: dict[str, Any]


def add_test_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("test", help="Run collection role smoke tests.")
    ssp = p.add_subparsers(dest="test_cmd", required=True)

    q = ssp.add_parser("role", help="Run a role smoke playbook from a collections workspace.")
    q.add_argument("role", help="Role FQCN (`hybridops.<collection>.<role>`) or unique role name.")
    q.add_argument("--root", default=None, help="Override runtime root.")
    q.add_argument("--env", default=None, help="Runtime environment namespace.")
    q.add_argument(
        "--workspace-root",
        default=None,
        help="Collections workspace root (defaults to HYOPS_COLLECTIONS_WORKSPACE or autodiscovery).",
    )
    q.add_argument(
        "--manifest",
        default=None,
        help="Override role smoke manifest path (defaults to tests/hyops.role-test.yml when present).",
    )
    q.add_argument(
        "--playbook",
        default=None,
        help="Override smoke playbook path (absolute, or relative to the role/tests directory).",
    )
    q.add_argument(
        "--inventory-file",
        default=None,
        help="Use an explicit inventory file instead of a state-backed generated inventory.",
    )
    q.add_argument(
        "--local-inventory",
        action="store_true",
        help="Force auto-detection of a real inventory file under role tests/.",
    )
    q.add_argument(
        "--inventory-state-ref",
        default=None,
        help="Resolve inventory from HybridOps state (for example: platform/onprem/platform-vm#rke2_vms).",
    )
    q.add_argument(
        "--inventory-vm-group",
        action="append",
        default=[],
        help="Map an inventory group to VM keys from the state ref (format: group=vm1,vm2).",
    )
    q.add_argument(
        "--inventory-input",
        action="append",
        default=[],
        help="Additional inventory input override (format: key=value).",
    )
    q.add_argument(
        "--extra-var",
        action="append",
        default=[],
        help="Extra playbook variable override (format: key=value).",
    )
    q.add_argument(
        "--required-env",
        action="append",
        default=[],
        help="Additional required environment variable name.",
    )
    q.add_argument(
        "--vault-env",
        action="store_true",
        help="Load missing required env vars and SSH key material from the runtime vault.",
    )
    q.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip ansible-galaxy dependency sync from the target collection requirements.yml.",
    )
    q.add_argument(
        "--ansible-arg",
        action="append",
        default=[],
        help="Additional raw ansible-playbook argument.",
    )
    mode = q.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Run ansible-playbook in check mode.")
    mode.add_argument("--syntax-check", action="store_true", help="Run ansible-playbook --syntax-check only.")
    q.add_argument("--json", action="store_true", help="Emit JSON output.")
    q.set_defaults(_handler=run_test_role)


def _emit_json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return OK


def _parse_scalar(raw: str) -> Any:
    token = str(raw).strip()
    if token == "":
        return ""
    try:
        return yaml.safe_load(token)
    except Exception:
        return token


def _parse_key_value(token: str, *, label: str) -> tuple[str, Any]:
    raw = str(token or "").strip()
    if "=" not in raw:
        raise ValueError(f"{label} must use key=value syntax")
    key, value = raw.split("=", 1)
    key = str(key or "").strip()
    if not key:
        raise ValueError(f"{label} key is empty")
    return key, _parse_scalar(value)


def _parse_vm_groups(tokens: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for token in list(tokens or []):
        raw = str(token or "").strip()
        if "=" not in raw:
            raise ValueError("--inventory-vm-group must use group=vm1,vm2 syntax")
        group, raw_items = raw.split("=", 1)
        group = str(group or "").strip()
        if not group:
            raise ValueError("--inventory-vm-group group is empty")
        values = [item.strip() for item in raw_items.split(",") if item.strip()]
        if not values:
            raise ValueError(f"--inventory-vm-group {group!r} must include at least one VM key")
        existing = out.setdefault(group, [])
        for item in values:
            if item not in existing:
                existing.append(item)
    return out


def _merge_string_list(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in list(group or []):
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            out.append(token)
    return out


def _workspace_collection_dirs(workspace_root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for child in sorted(workspace_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        match = _WORKSPACE_COLLECTION_RE.match(child.name)
        if not match:
            continue
        out[match.group(1)] = child.resolve()
    return out


def _resolve_role_target(workspace_root: Path, raw_role: str) -> RoleTarget:
    role_token = str(raw_role or "").strip()
    if not role_token:
        raise ValueError("role is required")

    collection_dirs = _workspace_collection_dirs(workspace_root)
    if not collection_dirs:
        raise FileNotFoundError(f"no collection workspaces found under {workspace_root}")

    parts = role_token.split(".")
    collection = ""
    role = ""
    if len(parts) == 3 and parts[0] == "hybridops":
        collection = str(parts[1] or "").strip()
        role = str(parts[2] or "").strip()
    elif len(parts) == 2 and parts[0] != "hybridops":
        collection = str(parts[0] or "").strip()
        role = str(parts[1] or "").strip()
    else:
        role = role_token

    if collection:
        collection_root = collection_dirs.get(collection)
        if collection_root is None:
            raise FileNotFoundError(f"collection workspace not found for {collection!r} under {workspace_root}")
        role_dir = (collection_root / "roles" / role).resolve()
        if not role_dir.exists():
            raise FileNotFoundError(f"role {role!r} not found in collection {collection!r}")
        return RoleTarget(
            collection=collection,
            role=role,
            fqcn=f"hybridops.{collection}.{role}",
            collection_root=collection_root,
            role_dir=role_dir,
        )

    if not _ROLE_REF_RE.fullmatch(role):
        raise ValueError(f"invalid role name: {role_token!r}")

    matches: list[RoleTarget] = []
    for candidate_collection, collection_root in sorted(collection_dirs.items()):
        role_dir = (collection_root / "roles" / role).resolve()
        if role_dir.exists():
            matches.append(
                RoleTarget(
                    collection=candidate_collection,
                    role=role,
                    fqcn=f"hybridops.{candidate_collection}.{role}",
                    collection_root=collection_root,
                    role_dir=role_dir,
                )
            )
    if not matches:
        raise FileNotFoundError(f"role {role!r} was not found in {workspace_root}")
    if len(matches) > 1:
        options = ", ".join(item.fqcn for item in matches)
        raise ValueError(f"role name {role!r} is ambiguous; use a full role ref ({options})")
    return matches[0]


def _resolve_existing_path(raw: str, *, bases: list[Path]) -> Path:
    token = str(raw or "").strip()
    if not token:
        raise ValueError("path is empty")
    candidate = Path(token).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not resolved.exists():
            raise FileNotFoundError(resolved)
        return resolved
    for base in bases:
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    resolved = (Path.cwd() / candidate).resolve()
    if resolved.exists():
        return resolved
    raise FileNotFoundError(token)


def _load_manifest(role_target: RoleTarget, raw_path: str | None) -> RoleSmokeManifest:
    manifest_path: Path | None = None
    if str(raw_path or "").strip():
        manifest_path = _resolve_existing_path(
            str(raw_path),
            bases=[role_target.role_dir / "tests", role_target.role_dir, role_target.collection_root],
        )
    else:
        default_path = (role_target.role_dir / "tests" / _DEFAULT_MANIFEST).resolve()
        if default_path.exists():
            manifest_path = default_path

    if manifest_path is None:
        return RoleSmokeManifest(path=None, payload={})

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"role smoke manifest must be a mapping: {manifest_path}")

    kind = str(payload.get("kind") or "").strip().lower()
    if kind and kind not in {"role-smoke", "hyops-role-smoke"}:
        raise ValueError(f"unsupported role smoke manifest kind {kind!r} in {manifest_path}")

    manifest_role = str(payload.get("role_fqcn") or "").strip()
    if manifest_role and manifest_role != role_target.fqcn:
        raise ValueError(
            f"role smoke manifest {manifest_path} targets {manifest_role}, expected {role_target.fqcn}"
        )

    return RoleSmokeManifest(path=manifest_path, payload=payload)


def _resolve_playbook(role_target: RoleTarget, manifest: RoleSmokeManifest, raw_path: str | None) -> Path:
    chosen = str(raw_path or "").strip() or str(manifest.payload.get("playbook") or "").strip() or "smoke.yml"
    return _resolve_existing_path(
        chosen,
        bases=[role_target.role_dir / "tests", role_target.role_dir, role_target.collection_root],
    )


def _auto_detect_local_inventory(role_target: RoleTarget) -> Path:
    tests_dir = (role_target.role_dir / "tests").resolve()
    candidates: list[Path] = []
    if tests_dir.exists():
        for candidate in sorted(tests_dir.rglob("*")):
            if not candidate.is_file():
                continue
            if ".ansible" in candidate.parts:
                continue
            name = candidate.name
            if name not in _INVENTORY_FILE_NAMES:
                parent_names = {part.lower() for part in candidate.parts}
                if candidate.suffix.lower() not in {".ini", ".yml", ".yaml"}:
                    continue
                if "inventory" not in parent_names and "inventories" not in parent_names:
                    continue
            candidates.append(candidate.resolve())

    if not candidates:
        raise FileNotFoundError(f"no local inventory file found under {tests_dir}")

    def _rank(path: Path) -> tuple[int, str]:
        lowered = path.name.lower()
        if lowered in {"inventory.ini", "hosts.ini"}:
            return (0, str(path))
        if lowered in {"inventory.yml", "inventory.yaml", "hosts.yml", "hosts.yaml"}:
            return (1, str(path))
        if lowered.startswith("inventory.sample."):
            return (3, str(path))
        if lowered.startswith("inventory.example."):
            return (4, str(path))
        parent_names = {part.lower() for part in path.parts}
        if "inventory" in parent_names or "inventories" in parent_names:
            return (2, str(path))
        return (5, str(path))

    ranked = sorted(candidates, key=_rank)
    best_rank = _rank(ranked[0])[0]
    best = [item for item in ranked if _rank(item)[0] == best_rank]
    if len(best) > 1:
        listing = ", ".join(str(item) for item in best)
        raise ValueError(f"multiple local inventory files found; use --inventory-file explicitly ({listing})")
    return best[0]


def _manifest_inventory(manifest: RoleSmokeManifest) -> dict[str, Any]:
    raw = manifest.payload.get("inventory")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("role smoke manifest inventory must be a mapping")
    return dict(raw)


def _as_mapping(raw: Any, *, label: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping")
    return dict(raw)


def _as_list(raw: Any, *, label: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    out: list[str] = []
    for idx, item in enumerate(raw, start=1):
        token = str(item or "").strip()
        if not token:
            raise ValueError(f"{label}[{idx}] must be a non-empty string")
        out.append(token)
    return out


def _build_inventory_inputs(
    *,
    ns,
    manifest: RoleSmokeManifest,
    paths,
    workdir: Path,
) -> tuple[Path, dict[str, Any], str]:
    manifest_inventory = _manifest_inventory(manifest)

    explicit_inventory_file = str(getattr(ns, "inventory_file", None) or "").strip()
    if explicit_inventory_file:
        role_target = getattr(ns, "_role_target")
        inventory_path = _resolve_existing_path(
            explicit_inventory_file,
            bases=[role_target.role_dir / "tests", role_target.role_dir, role_target.collection_root, Path.cwd()],
        )
        return inventory_path, {}, "explicit-file"

    inventory_inputs = _as_mapping(manifest_inventory.get("inputs"), label="manifest inventory.inputs")
    for token in list(getattr(ns, "inventory_input", []) or []):
        key, value = _parse_key_value(str(token), label="--inventory-input")
        inventory_inputs[key] = value

    if getattr(ns, "local_inventory", False):
        role_target = getattr(ns, "_role_target")
        inventory_path = _auto_detect_local_inventory(role_target)
        return inventory_path, inventory_inputs, "local-file"

    manifest_file = str(manifest_inventory.get("file") or "").strip()
    if manifest_file:
        role_target = getattr(ns, "_role_target")
        inventory_path = _resolve_existing_path(
            manifest_file,
            bases=[role_target.role_dir / "tests", role_target.role_dir, role_target.collection_root],
        )
        return inventory_path, inventory_inputs, "manifest-file"

    inventory_state_ref = str(getattr(ns, "inventory_state_ref", None) or "").strip()
    if not inventory_state_ref:
        inventory_state_ref = str(manifest_inventory.get("state_ref") or "").strip()

    vm_groups = _as_mapping(manifest_inventory.get("vm_groups"), label="manifest inventory.vm_groups")
    cli_groups = _parse_vm_groups(list(getattr(ns, "inventory_vm_group", []) or []))
    for group, items in cli_groups.items():
        vm_groups[group] = list(items)

    if inventory_state_ref:
        inventory_inputs["inventory_state_ref"] = inventory_state_ref
        if vm_groups:
            inventory_inputs["inventory_vm_groups"] = vm_groups
        resolve_inventory_groups_from_state(inventory_inputs, state_root=paths.state_dir)
        inventory_path = (workdir / "inventory.ini").resolve()
        inventory_error = write_inventory(inventory_path, inventory_inputs)
        if inventory_error:
            raise ValueError(inventory_error)
        return inventory_path, inventory_inputs, "generated-from-state"

    role_target = getattr(ns, "_role_target")
    inventory_path = _auto_detect_local_inventory(role_target)
    return inventory_path, inventory_inputs, "auto-file"


def _build_workspace_overlay(workspace_root: Path, workdir: Path) -> Path:
    overlay_root = (workdir / "collections").resolve()
    namespace_root = overlay_root / "ansible_collections" / "hybridops"
    namespace_root.mkdir(parents=True, exist_ok=True)
    for collection, source in _workspace_collection_dirs(workspace_root).items():
        target = namespace_root / collection
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source, target_is_directory=True)
    return overlay_root


def _prepend_env_path(env: dict[str, str], key: str, value: str) -> None:
    token = str(value or "").strip()
    if not token:
        return
    existing = str(env.get(key) or "").strip()
    parts = [p for p in existing.split(os.pathsep) if p] if existing else []
    if token in parts:
        parts.remove(token)
    parts.insert(0, token)
    env[key] = os.pathsep.join(parts)


def _sync_collection_requirements(
    *,
    collection_root: Path,
    env: dict[str, str],
    evidence_dir: Path,
    controller_python: str,
    collections_cache_root: Path,
    roles_cache_root: Path,
) -> None:
    req_path = (collection_root / "requirements.yml").resolve()
    if not req_path.exists():
        return

    payload = yaml.safe_load(req_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"collection requirements must be a mapping: {req_path}")

    collections_cache_root.mkdir(parents=True, exist_ok=True)
    roles_cache_root.mkdir(parents=True, exist_ok=True)

    python_bin = str(controller_python or sys.executable).strip()
    if not python_bin:
        raise ValueError("unable to resolve Python interpreter for ansible-galaxy")

    if isinstance(payload.get("collections"), list) and payload.get("collections"):
        proc = subprocess.run(
            [
                python_bin,
                "-m",
                "ansible.cli.galaxy",
                "collection",
                "install",
                "-r",
                str(req_path),
                "-p",
                str(collections_cache_root),
                "--upgrade",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        (evidence_dir / "ansible_galaxy_collection_install.stdout.txt").write_text(
            proc.stdout or "",
            encoding="utf-8",
        )
        (evidence_dir / "ansible_galaxy_collection_install.stderr.txt").write_text(
            proc.stderr or "",
            encoding="utf-8",
        )
        if int(proc.returncode or 0) != 0:
            raise RuntimeError(
                "ansible-galaxy collection install failed "
                f"(open: {(evidence_dir / 'ansible_galaxy_collection_install.stderr.txt').resolve()})"
            )

    if isinstance(payload.get("roles"), list) and payload.get("roles"):
        proc = subprocess.run(
            [
                python_bin,
                "-m",
                "ansible.cli.galaxy",
                "role",
                "install",
                "-r",
                str(req_path),
                "-p",
                str(roles_cache_root),
                "--force",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        (evidence_dir / "ansible_galaxy_role_install.stdout.txt").write_text(
            proc.stdout or "",
            encoding="utf-8",
        )
        (evidence_dir / "ansible_galaxy_role_install.stderr.txt").write_text(
            proc.stderr or "",
            encoding="utf-8",
        )
        if int(proc.returncode or 0) != 0:
            raise RuntimeError(
                "ansible-galaxy role install failed "
                f"(open: {(evidence_dir / 'ansible_galaxy_role_install.stderr.txt').resolve()})"
            )


def run_test_role(ns) -> int:
    try:
        require_runtime_selection(ns.root, ns.env, command_label="hyops test role")
        paths = resolve_runtime_paths(ns.root, ns.env)
        ensure_layout(paths)
    except Exception as exc:
        if getattr(ns, "json", False):
            return _emit_json({"ok": False, "error": str(exc)})
        print(f"ERR: {exc}", file=sys.stderr)
        return OPERATOR_ERROR

    workspace_root = discover_collections_workspace(getattr(ns, "workspace_root", None))
    if workspace_root is None:
        msg = (
            "unable to discover collections workspace. "
            "Set --workspace-root <path> or HYOPS_COLLECTIONS_WORKSPACE."
        )
        if getattr(ns, "json", False):
            return _emit_json({"ok": False, "error": msg})
        print(f"ERR: {msg}", file=sys.stderr)
        return OPERATOR_ERROR

    try:
        role_target = _resolve_role_target(workspace_root, getattr(ns, "role", ""))
        setattr(ns, "_role_target", role_target)
        manifest = _load_manifest(role_target, getattr(ns, "manifest", None))
        playbook_path = _resolve_playbook(role_target, manifest, getattr(ns, "playbook", None))
    except Exception as exc:
        if getattr(ns, "json", False):
            return _emit_json({"ok": False, "error": str(exc)})
        print(f"ERR: {exc}", file=sys.stderr)
        return OPERATOR_ERROR

    run_id = new_run_id("test-role")
    evidence_root = paths.logs_dir / "test" / "role" / role_target.collection / role_target.role
    evidence_dir = init_evidence_dir(evidence_root, run_id)
    workdir = (paths.work_dir / "test" / "role" / f"{role_target.collection}__{role_target.role}" / run_id).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    ev = EvidenceWriter(evidence_dir)

    env = os.environ.copy()
    env["HYOPS_RUNTIME_ROOT"] = str(paths.root)
    if str(getattr(ns, "env", "") or "").strip():
        env["HYOPS_ENV"] = str(ns.env).strip()
    env.setdefault("HYOPS_EXECUTABLE", _resolve_hyops_executable())

    ansible_bin = str(shutil.which("ansible-playbook") or "").strip()
    if not ansible_bin:
        msg = "missing command: ansible-playbook"
        print(f"ERR: {msg}", file=sys.stderr)
        return DEPENDENCY_MISSING

    dep_error = prepare_ansible_controller_env(env=env, runtime_root=paths.root, ansible_bin=ansible_bin)
    if dep_error:
        print(f"ERR: {dep_error}", file=sys.stderr)
        return DEPENDENCY_MISSING

    try:
        inventory_path, inventory_inputs, inventory_source = _build_inventory_inputs(
            ns=ns,
            manifest=manifest,
            paths=paths,
            workdir=workdir,
        )
    except Exception as exc:
        if getattr(ns, "json", False):
            return _emit_json({"ok": False, "error": str(exc)})
        print(f"ERR: {exc}", file=sys.stderr)
        return OPERATOR_ERROR

    try:
        required_env = _merge_string_list(
            _as_list(manifest.payload.get("required_env"), label="manifest required_env"),
            list(getattr(ns, "required_env", []) or []),
        )
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return OPERATOR_ERROR

    needs_vault_env = bool(getattr(ns, "vault_env", False))
    if str(inventory_inputs.get("ssh_private_key_env") or "").strip():
        needs_vault_env = True

    # Keep role smoke runs deterministic. Ambient workstation vault helpers should
    # not force decryption paths unless this command explicitly needs runtime
    # vault material.
    if not needs_vault_env:
        env.pop("ANSIBLE_VAULT_PASSWORD_FILE", None)

    enforce_required_env = not bool(getattr(ns, "syntax_check", False))

    if needs_vault_env or (enforce_required_env and missing_env(env, required_env)):
        _loaded, vault_error = merge_vault_env(env, paths.root)
        if vault_error:
            print(f"ERR: {vault_error}", file=sys.stderr)
            return SECRETS_FAILED

    try:
        if inventory_inputs:
            materialize_ssh_private_key_from_env(inputs=inventory_inputs, env=env, workdir=workdir)
            if inventory_source == "generated-from-state":
                inventory_error = write_inventory(inventory_path, inventory_inputs)
                if inventory_error:
                    raise ValueError(inventory_error)
    except Exception as exc:
        print(f"ERR: failed to materialize runtime SSH key: {exc}", file=sys.stderr)
        return SECRETS_FAILED

    if enforce_required_env:
        missing_required = missing_env(env, required_env)
        if missing_required:
            missing_list = ", ".join(missing_required)
            print(
                f"ERR: missing required env vars: {missing_list}. "
                f"Provide them via shell env or runtime vault for env {str(getattr(ns, 'env', '') or '<root>').strip()}",
                file=sys.stderr,
            )
            return SECRETS_FAILED

    collections_overlay = _build_workspace_overlay(workspace_root, workdir)

    test_state_root = (paths.state_dir / "ansible" / "tests" / role_target.collection).resolve()
    collections_cache_root = (test_state_root / "galaxy_collections").resolve()
    roles_cache_root = (test_state_root / "roles").resolve()
    if not getattr(ns, "skip_deps", False):
        controller_python = resolve_ansible_controller_python(ansible_bin)
        try:
            _sync_collection_requirements(
                collection_root=role_target.collection_root,
                env=env,
                evidence_dir=evidence_dir,
                controller_python=controller_python,
                collections_cache_root=collections_cache_root,
                roles_cache_root=roles_cache_root,
            )
        except Exception as exc:
            print(f"ERR: {exc}", file=sys.stderr)
            return DEPENDENCY_MISSING

    result_envelope: dict[str, Any] = {"warnings": []}
    configure_ansible_search_paths(
        env=env,
        runtime_root=paths.root,
        module_id="test__role",
        ev=ev,
        result=result_envelope,
    )
    _prepend_env_path(env, "ANSIBLE_COLLECTIONS_PATH", str(collections_cache_root))
    _prepend_env_path(env, "ANSIBLE_COLLECTIONS_PATH", str(collections_overlay))
    _prepend_env_path(env, "ANSIBLE_ROLES_PATH", str(roles_cache_root))
    collections_error = ensure_hybridops_collections_available(env)
    if collections_error:
        print(f"ERR: {collections_error}", file=sys.stderr)
        return DEPENDENCY_MISSING

    ansible_cfg = (role_target.collection_root / "ansible.cfg").resolve()
    if ansible_cfg.exists():
        env["ANSIBLE_CONFIG"] = str(ansible_cfg)

    try:
        extra_vars = _as_mapping(manifest.payload.get("extra_vars"), label="manifest extra_vars")
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return OPERATOR_ERROR
    for token in list(getattr(ns, "extra_var", []) or []):
        key, value = _parse_key_value(str(token), label="--extra-var")
        extra_vars[key] = value
    extra_vars.setdefault("hyops_test_role", role_target.fqcn)
    extra_vars.setdefault("hyops_test_run_id", run_id)
    extra_vars.setdefault("hyops_test_workspace_root", str(workspace_root))

    extra_vars_path = (workdir / "hyops.test.inputs.yml").resolve()
    extra_vars_path.write_text(yaml.safe_dump(extra_vars, sort_keys=True), encoding="utf-8")

    args = [str(item) for item in list(getattr(ns, "ansible_arg", []) or []) if str(item or "").strip()]
    label = "ansible_test_role"
    if getattr(ns, "syntax_check", False):
        args = ["--syntax-check", *args]
        label = "ansible_test_syntax"
    elif getattr(ns, "check", False):
        args = ["--check", "--diff", *args]
        label = "ansible_test_check"

    argv = build_playbook_argv(
        ansible_bin=ansible_bin,
        playbook_path=playbook_path,
        inventory_path=inventory_path,
        extra_vars_path=extra_vars_path,
        args=args,
    )

    meta = {
        "role_fqcn": role_target.fqcn,
        "workspace_root": str(workspace_root),
        "collection_root": str(role_target.collection_root),
        "role_dir": str(role_target.role_dir),
        "playbook": str(playbook_path),
        "manifest": str(manifest.path) if manifest.path else "",
        "inventory": {
            "source": inventory_source,
            "path": str(inventory_path),
            "state_ref": str(inventory_inputs.get("inventory_state_ref") or ""),
            "vm_groups": inventory_inputs.get("inventory_vm_groups") if isinstance(inventory_inputs.get("inventory_vm_groups"), dict) else {},
        },
        "required_env": required_env,
        "workdir": str(workdir),
        "run_id": run_id,
    }
    ev.write_json("meta.json", meta)

    proc = run_capture_with_policy(
        argv=argv,
        cwd=str(role_target.collection_root),
        env=env,
        evidence_dir=evidence_dir,
        label=label,
        timeout_s=None,
        redact=True,
        retries=0,
    )

    payload = {
        "status": "ok" if int(proc.rc) == 0 else "error",
        "run_id": run_id,
        "role_fqcn": role_target.fqcn,
        "playbook": str(playbook_path),
        "inventory": str(inventory_path),
        "run_record": str(evidence_dir),
    }
    ev.write_json("result.json", payload)

    if getattr(ns, "json", False):
        return _emit_json(payload)

    print(f"role={role_target.fqcn} status={payload['status']} run_id={run_id}")
    print(f"playbook: {playbook_path}")
    print(f"inventory: {inventory_path}")
    print(f"run record: {evidence_dir}")
    if int(proc.rc) != 0:
        print(f"ERR: ansible-playbook failed (open: {(evidence_dir / 'ansible.log').resolve()})", file=sys.stderr)
        return REMOTE_FAILED
    return OK


__all__ = ["add_test_subparser", "run_test_role"]
