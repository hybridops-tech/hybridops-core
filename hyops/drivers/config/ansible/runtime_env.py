"""Runtime env preparation helpers for the Ansible config driver."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.vault import VaultAuth, read_env

from .hotfixes import apply_collection_hotfixes


_MODULE_ID_ALIASES: dict[str, tuple[str, ...]] = {
    "platform__postgresql-ha": ("platform__onprem__postgresql-ha",),
    "platform__onprem__postgresql-ha": ("platform__postgresql-ha",),
    "platform__postgresql-ha-backup": ("platform__onprem__postgresql-ha-backup",),
    "platform__onprem__postgresql-ha-backup": ("platform__postgresql-ha-backup",),
}


def _append_search_path(out: list[str], raw_path: str) -> None:
    """Append a search-path entry once, preserving non-existent default locations."""
    raw = str(raw_path or "").strip()
    if not raw:
        return
    candidate = str(Path(raw).expanduser())
    if candidate not in out:
        out.append(candidate)


def _extend_search_path(out: list[str], raw_path: str) -> None:
    """Split a colon-delimited search path and append each entry once."""
    for token in str(raw_path or "").split(":"):
        _append_search_path(out, token)


def _collection_search_roots(raw_path: str) -> list[Path]:
    roots: list[Path] = []
    for token in str(raw_path or "").split(":"):
        raw = str(token or "").strip()
        if not raw:
            continue
        roots.append(Path(raw).expanduser())
    return roots


def _has_hybridops_collection(raw_path: str) -> bool:
    for root in _collection_search_roots(raw_path):
        candidates = [root] if root.name == "ansible_collections" else [root / "ansible_collections"]
        for candidate in candidates:
            if (candidate / "hybridops").is_dir():
                return True
    return False


def allow_vendored_collection_fallback(env: dict[str, str]) -> bool:
    raw = str(env.get("HYOPS_INTERNAL_ALLOW_VENDORED_COLLECTION_FALLBACK") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _iter_collection_role_dirs(collection_roots: list[str]) -> list[str]:
    """Derive collection role directories for use as a robust role-resolution fallback.

    Some remote-play contexts in ansible-core 2.18 can fail to resolve collection
    roles reliably via include_role/FQCN even when ANSIBLE_COLLECTIONS_PATH is set
    correctly. Adding discovered collection role directories to ANSIBLE_ROLES_PATH
    gives the driver a deterministic fallback without changing pack authorship.
    """

    out: list[str] = []
    seen: set[str] = set()
    for token in collection_roots:
        base = Path(token).expanduser()
        candidates = [base] if base.name == "ansible_collections" else [base / "ansible_collections"]
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            for namespace_dir in sorted(candidate.iterdir()):
                if not namespace_dir.is_dir():
                    continue
                for collection_dir in sorted(namespace_dir.iterdir()):
                    roles_dir = collection_dir / "roles"
                    if not roles_dir.is_dir():
                        continue
                    resolved = str(roles_dir)
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    out.append(resolved)
    return out


def resolve_ansible_controller_python(ansible_bin: str) -> str:
    """Best-effort resolve of the Python interpreter used by ansible-playbook."""
    resolved = str(shutil.which(ansible_bin) or ansible_bin).strip()
    if not resolved:
        return ""
    path = Path(resolved).expanduser().resolve()
    if not path.exists():
        return ""

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            first = str(fh.readline() or "").strip()
    except Exception:
        return ""
    if not first.startswith("#!"):
        return ""

    shebang = first[2:].strip()
    if not shebang:
        return ""
    parts = shlex.split(shebang)
    if not parts:
        return ""

    launcher = parts[0]
    if Path(launcher).name == "env":
        if len(parts) < 2:
            return ""
        return str(shutil.which(parts[1]) or "").strip()
    return launcher


def prepare_ansible_controller_env(*, env: dict[str, str], runtime_root: Path, ansible_bin: str) -> str:
    """Set temp paths, vendor required python deps, and validate controller imports."""
    tmp_dir = runtime_root / "tmp"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    env.setdefault("TMPDIR", str(tmp_dir))
    env.setdefault("ANSIBLE_LOCAL_TEMP", str(tmp_dir / "ansible-local"))
    # Use a world-writable base so tasks can switch become_user (e.g. postgres).
    env.setdefault("ANSIBLE_REMOTE_TEMP", "/tmp")
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    env.setdefault("ANSIBLE_TIMEOUT", "30")

    # Some Ansible filters (notably json_query) require Python deps like jmespath.
    # Autobase references json_query even in tasks that will be skipped, so the
    # dependency must still be importable by the ansible-playbook runtime.
    #
    # Do NOT add system dist-packages directly to PYTHONPATH (it can shadow pipx
    # Ansible with the OS Ansible). Instead, vendor only the required packages.
    vendor_dir = runtime_root / "state" / "python" / "vendor"
    vendor_pkgs = ("jmespath", "netaddr")
    controller_python = resolve_ansible_controller_python(ansible_bin)
    search_roots: list[Path] = []

    def _add_search_root(path: Path) -> None:
        if not path.is_dir():
            return
        try:
            real = path.resolve()
        except Exception:
            real = path
        if real not in search_roots:
            search_roots.append(real)

    # System Python locations.
    _add_search_root(Path("/usr/lib/python3/dist-packages"))
    _add_search_root(Path("/usr/local/lib/python3/dist-packages"))

    # pipx-managed Ansible envs.
    pipx_root = Path("/opt/pipx/venvs")
    if pipx_root.is_dir():
        for site in sorted(pipx_root.glob("*/lib/python*/site-packages")):
            _add_search_root(site)

    # Controller interpreter site-packages (derived from ansible-playbook shebang).
    if controller_python:
        ctrl = Path(controller_python).expanduser()
        for site in sorted((ctrl.parent.parent / "lib").glob("python*/site-packages")):
            _add_search_root(site)

    for pkg in vendor_pkgs:
        dst = vendor_dir / pkg
        if dst.is_dir():
            continue
        for root in search_roots:
            src = root / pkg
            if not src.is_dir():
                continue
            try:
                vendor_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst, dirs_exist_ok=True)
            except Exception:
                pass
            break

    if any((vendor_dir / pkg).is_dir() for pkg in vendor_pkgs):
        py_path = str(env.get("PYTHONPATH") or "").strip()
        parts = [p for p in py_path.split(os.pathsep) if p] if py_path else []
        vend = str(vendor_dir)
        if vend not in parts:
            parts.insert(0, vend)
            env["PYTHONPATH"] = os.pathsep.join(parts)

    # Fail fast before running playbooks when required controller-side Python
    # deps are still missing. This avoids opaque runtime task failures.
    if controller_python:
        probe_script = (
            "import importlib.util,sys;"
            "mods=('jmespath','netaddr');"
            "missing=[m for m in mods if importlib.util.find_spec(m) is None];"
            "print(','.join(missing));"
            "raise SystemExit(0 if not missing else 2)"
        )
        try:
            probe = subprocess.run(
                [controller_python, "-c", probe_script],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except Exception as exc:
            return f"unable to verify ansible controller dependencies: {exc}"
        if int(probe.returncode or 0) != 0:
            missing = str(probe.stdout or "").strip() or ",".join(vendor_pkgs)
            details = str(probe.stderr or "").strip().splitlines()
            extra = f" ({details[0]})" if details else ""
            return (
                "missing ansible controller python dependencies: "
                f"{missing}; run: hyops setup base --sudo{extra}"
            )

    return ""


def configure_ansible_search_paths(
    *,
    env: dict[str, str],
    runtime_root: Path,
    module_id: str,
    vendored_collections_dir: Path,
    ev: EvidenceWriter,
    result: dict[str, Any],
) -> None:
    module_ids = [module_id, *[alias for alias in _MODULE_ID_ALIASES.get(module_id, ()) if alias and alias != module_id]]

    roles_path_parts: list[str] = []
    for candidate_module_id in module_ids:
        module_roles = runtime_root / "state" / "ansible" / "modules" / candidate_module_id / "roles"
        if module_roles.is_dir():
            _append_search_path(roles_path_parts, str(module_roles))
    runtime_roles = runtime_root / "state" / "ansible" / "roles"
    if runtime_roles.is_dir():
        _append_search_path(roles_path_parts, str(runtime_roles))

    # Workstation install flow typically installs shared deps into ~/.hybridops (global).
    # When running with --env, include global fallback paths so operators don't need to
    # install deps per-environment.
    global_root = (Path.home() / ".hybridops").resolve()
    if global_root != runtime_root:
        for candidate_module_id in module_ids:
            global_module_roles = global_root / "state" / "ansible" / "modules" / candidate_module_id / "roles"
            if global_module_roles.is_dir():
                _append_search_path(roles_path_parts, str(global_module_roles))
        global_roles = global_root / "state" / "ansible" / "roles"
        if global_roles.is_dir():
            _append_search_path(roles_path_parts, str(global_roles))

    collections_path_parts: list[str] = []
    for candidate_module_id in module_ids:
        module_collections = runtime_root / "state" / "ansible" / "modules" / candidate_module_id / "galaxy_collections"
        if not module_collections.is_dir():
            module_collections = runtime_root / "state" / "ansible" / "modules" / candidate_module_id / "collections"
        if module_collections.is_dir():
            _append_search_path(collections_path_parts, str(module_collections))

    runtime_collections = runtime_root / "state" / "ansible" / "galaxy_collections"
    if not runtime_collections.is_dir():
        runtime_collections = runtime_root / "state" / "ansible" / "collections"
    if runtime_collections.is_dir():
        _append_search_path(collections_path_parts, str(runtime_collections))

    if global_root != runtime_root:
        for candidate_module_id in module_ids:
            global_module_collections = global_root / "state" / "ansible" / "modules" / candidate_module_id / "galaxy_collections"
            if not global_module_collections.is_dir():
                global_module_collections = global_root / "state" / "ansible" / "modules" / candidate_module_id / "collections"
            if global_module_collections.is_dir():
                _append_search_path(collections_path_parts, str(global_module_collections))

        global_collections = global_root / "state" / "ansible" / "galaxy_collections"
        if not global_collections.is_dir():
            global_collections = global_root / "state" / "ansible" / "collections"
        if global_collections.is_dir():
            _append_search_path(collections_path_parts, str(global_collections))
    if allow_vendored_collection_fallback(env) and vendored_collections_dir.is_dir():
        _append_search_path(collections_path_parts, str(vendored_collections_dir))
    # Preserve operator overrides if present, otherwise include sane defaults.
    collections_path_tail = str(env.get("ANSIBLE_COLLECTIONS_PATH") or env.get("ANSIBLE_COLLECTIONS_PATHS") or "").strip()
    if not collections_path_tail:
        collections_path_tail = f"{Path.home()}/.ansible/collections:/usr/share/ansible/collections"
    _extend_search_path(collections_path_parts, collections_path_tail)

    if collections_path_parts:
        env["ANSIBLE_COLLECTIONS_PATH"] = ":".join(collections_path_parts)
        env.pop("ANSIBLE_COLLECTIONS_PATHS", None)

    for collection_roles_dir in _iter_collection_role_dirs(collections_path_parts):
        _append_search_path(roles_path_parts, collection_roles_dir)

    # Preserve operator overrides if present, otherwise include sane defaults.
    # Note: setting ANSIBLE_ROLES_PATH overrides Ansible defaults, so we must
    # keep default locations in the search path.
    roles_path_tail = str(env.get("ANSIBLE_ROLES_PATH") or "").strip()
    if not roles_path_tail:
        roles_path_tail = f"{Path.home()}/.ansible/roles:/etc/ansible/roles"
    _extend_search_path(roles_path_parts, roles_path_tail)

    if roles_path_parts:
        env["ANSIBLE_ROLES_PATH"] = ":".join(roles_path_parts)

    apply_collection_hotfixes(ev=ev, result=result, env=env)


def ensure_hybridops_collections_available(env: dict[str, str]) -> str:
    collections_path = str(env.get("ANSIBLE_COLLECTIONS_PATH") or env.get("ANSIBLE_COLLECTIONS_PATHS") or "").strip()
    if _has_hybridops_collection(collections_path):
        return ""
    return "missing HybridOps Ansible collections; run: hyops setup ansible"


def merge_vault_env(env: dict[str, str], runtime_root: Path) -> tuple[dict[str, str], str]:
    vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
    if not vault_file.exists():
        return {}, ""

    try:
        vault_env = read_env(vault_file, VaultAuth())
    except Exception as exc:
        return {}, f"vault decrypt failed: {exc}"

    # Env precedence: keep explicit env vars set by operator.
    for k, v in vault_env.items():
        if (env.get(k) or "").strip():
            continue
        env[k] = str(v)

    return vault_env, ""


def missing_env(env: dict[str, str], required: list[str]) -> list[str]:
    missing: list[str] = []
    for key in required:
        if not (env.get(key) or "").strip():
            missing.append(key)
    return missing


def materialize_ssh_private_key_from_env(
    *,
    inputs: dict[str, Any],
    env: dict[str, str],
    workdir: Path,
) -> str:
    key_file_raw = str(inputs.get("ssh_private_key_file") or "").strip()
    key_env_name = str(inputs.get("ssh_private_key_env") or "").strip()

    if not key_env_name:
        return ""

    key_value = str(env.get(key_env_name) or "").strip()
    if not key_value:
        return ""

    if (
        "\\n" in key_value
        and "-----BEGIN " in key_value
        and " PRIVATE KEY-----" in key_value
    ):
        key_value = key_value.replace("\\r", "").replace("\\n", "\n").strip()

    existing_ok = False
    if key_file_raw:
        try:
            existing_ok = Path(key_file_raw).expanduser().exists()
        except Exception:
            existing_ok = False
    if existing_ok:
        return ""

    key_path = (workdir / "runtime.ssh.key").resolve()
    key_path.write_text(key_value + ("\n" if not key_value.endswith("\n") else ""), encoding="utf-8")
    os.chmod(key_path, 0o600)
    inputs["ssh_private_key_file"] = str(key_path)
    return str(key_path)
