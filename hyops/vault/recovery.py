"""Guarded recovery for an inaccessible local HybridOps vault key."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hyops.blueprint.contracts import step_state_ref
from hyops.blueprint.schema import (
    load_blueprint,
    resolve_blueprint_file,
    validate_blueprint,
)
from hyops.commands._apply_helpers import load_module_spec
from hyops.runtime.exitcodes import CANCELLED, INTERNAL_ERROR, OPERATOR_ERROR
from hyops.runtime.module_state import read_module_state
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.source_roots import resolve_blueprints_root, resolve_module_root

_ENTRY = "hybridops/ansible-vault"
_KEY_UID = "HybridOps Vault (local)"


def _blueprint_details(ns) -> tuple[dict[str, Any], list[str]]:
    blueprints_root = resolve_blueprints_root(ns.blueprints_root)
    blueprint_file = resolve_blueprint_file(
        ref=str(ns.ref),
        file_path="",
        blueprints_root=blueprints_root,
    )
    payload = validate_blueprint(load_blueprint(blueprint_file), blueprint_file)
    return payload, list(payload.get("recoverable_secrets") or [])


def _required_env(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "required_env" and isinstance(item, list):
                found.extend(str(name).strip() for name in item if str(name).strip())
            else:
                found.extend(_required_env(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_required_env(item))
    return found


def _configured_secret_consumers(
    payload: dict[str, Any], state_dir: Path, modules_root: Path
) -> list[str]:
    protected = set(payload.get("recoverable_secrets") or [])
    if not protected:
        return []
    configured: list[str] = []
    for step in payload["steps"]:
        required = set(_required_env(step.get("inputs", {})))
        try:
            required.update(_required_env(load_module_spec(modules_root, step["module_ref"])))
        except Exception:
            pass
        if not required.intersection(protected):
            continue
        try:
            state = read_module_state(state_dir, step_state_ref(step))
        except Exception:
            continue
        if str(state.get("status") or "").strip().lower() == "ok":
            configured.append(step["id"])
    return configured


def _password_store_files(store: Path) -> list[str]:
    if not store.exists():
        return []
    files: list[str] = []
    for path in store.rglob("*"):
        if not path.is_file() or ".git" in path.relative_to(store).parts:
            continue
        files.append(path.relative_to(store).as_posix())
    return sorted(files)


def _other_environment_vaults(selected: Path) -> list[Path]:
    runtime_home = (Path.home() / ".hybridops").resolve()
    if not runtime_home.exists():
        return []
    selected = selected.resolve()
    found: list[Path] = []
    for path in runtime_home.glob("envs/*/vault/bootstrap.vault.env"):
        resolved = path.resolve()
        if resolved != selected:
            found.append(resolved)
    legacy = runtime_home / "vault" / "bootstrap.vault.env"
    if legacy.exists() and legacy.resolve() != selected:
        found.append(legacy.resolve())
    return sorted(found)


def _gpg_uid(fingerprint: str) -> str:
    completed = subprocess.run(
        ["gpg", "--with-colons", "--list-secret-keys", fingerprint],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    for line in completed.stdout.splitlines():
        fields = line.split(":")
        if fields and fields[0] == "uid" and len(fields) > 9:
            return fields[9]
    return ""


def _secret_key_fingerprints() -> list[str]:
    completed = subprocess.run(
        ["gpg", "--with-colons", "--list-secret-keys"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    fingerprints: list[str] = []
    waiting_for_fingerprint = False
    for line in completed.stdout.splitlines():
        fields = line.split(":")
        record_type = fields[0] if fields else ""
        if record_type == "sec":
            waiting_for_fingerprint = True
            continue
        if waiting_for_fingerprint and record_type == "fpr" and len(fields) > 9:
            fingerprints.append(fields[9])
            waiting_for_fingerprint = False
    return fingerprints


def _run(command: list[str]) -> int:
    try:
        return int(subprocess.run(command, check=False).returncode)
    except KeyboardInterrupt:
        return CANCELLED


def _backup(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def run_recover(ns, script: Path) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("ERR: vault recovery requires an interactive terminal.")
        return OPERATOR_ERROR
    for command in ("gpg", "gpgconf", "pass", "ansible-vault"):
        if not shutil.which(command):
            print(f"ERR: vault recovery requires {command}.")
            print("run: hyops setup base")
            return OPERATOR_ERROR

    try:
        payload, secret_keys = _blueprint_details(ns)
        paths = resolve_runtime_paths(None, ns.env)
    except Exception as exc:
        print(f"ERR: vault recovery preparation failed: {exc}")
        return OPERATOR_ERROR

    configured_consumers = _configured_secret_consumers(
        payload,
        paths.state_dir,
        resolve_module_root(ns.modules_root),
    )
    if configured_consumers:
        print(
            "ERR: generated credentials may already be active in deployed resources; "
            "automatic recovery stopped."
        )
        print("configured_steps: " + ", ".join(configured_consumers))
        return OPERATOR_ERROR
    if not secret_keys:
        print("ERR: this blueprint does not declare credentials that can be regenerated safely.")
        return OPERATOR_ERROR

    vault_file = paths.vault_dir / "bootstrap.vault.env"
    other_vaults = _other_environment_vaults(vault_file)
    if other_vaults:
        print(
            "ERR: the local vault password provider is shared by multiple environments; "
            "recovery stopped."
        )
        print("other_environment_vaults:")
        for path in other_vaults:
            print(f"  {path}")
        return OPERATOR_ERROR

    store = Path(
        os.environ.get("PASSWORD_STORE_DIR", str(Path.home() / ".password-store"))
    ).expanduser().resolve()
    expected_files = {".gpg-id", f"{_ENTRY}.gpg"}
    unexpected = sorted(set(_password_store_files(store)) - expected_files)
    if unexpected:
        print("ERR: password store contains entries not owned by HybridOps; recovery stopped.")
        print("entries:")
        for name in unexpected:
            print(f"  {name}")
        return OPERATOR_ERROR

    gpg_id_file = store / ".gpg-id"
    fingerprint = (
        gpg_id_file.read_text(encoding="utf-8").strip().splitlines()[0]
        if gpg_id_file.exists()
        else ""
    )
    if not fingerprint:
        print("ERR: HybridOps GPG identity could not be determined.")
        return OPERATOR_ERROR
    if _KEY_UID not in _gpg_uid(fingerprint):
        print("ERR: password store is not bound to the HybridOps local vault key.")
        return OPERATOR_ERROR
    other_keys = [item for item in _secret_key_fingerprints() if item != fingerprint]
    if other_keys:
        print("ERR: this GPG keyring contains keys not owned by HybridOps; recovery stopped.")
        return OPERATOR_ERROR

    print(f"environment: {ns.env}")
    print(f"blueprint: {payload['blueprint_ref']}")
    print("The inaccessible HybridOps key and encrypted environment vault will be replaced.")
    print("Cloud and on-premises resources will not be changed.")
    try:
        answer = input(f'Type "recover {ns.env}" to continue: ').strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return CANCELLED
    if answer != f"recover {ns.env}":
        print("vault recovery cancelled.")
        return CANCELLED

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery_dir = Path.home() / ".hybridops" / "recovery" / f"vault-{ns.env}-{stamp}"
    recovery_dir.mkdir(parents=True, mode=0o700)
    os.chmod(recovery_dir, 0o700)
    _backup(store, recovery_dir / "password-store")
    _backup(vault_file, recovery_dir / "bootstrap.vault.env")

    if _run([str(script), "--reset"]) != 0:
        print(f"ERR: vault entry reset failed; backup: {recovery_dir}")
        return INTERNAL_ERROR
    gpg_id_file.unlink(missing_ok=True)

    if _run(["gpg", "--batch", "--yes", "--delete-secret-key", fingerprint]) != 0:
        print(f"ERR: HybridOps secret-key removal failed; backup: {recovery_dir}")
        return INTERNAL_ERROR
    if _run(["gpg", "--batch", "--yes", "--delete-key", fingerprint]) != 0:
        print(f"ERR: HybridOps public-key removal failed; backup: {recovery_dir}")
        return INTERNAL_ERROR
    _run(["gpgconf", "--kill", "gpg-agent"])
    vault_file.unlink(missing_ok=True)

    print("Create the replacement HybridOps key and vault password.")
    if _run(
        [
            sys.executable,
            "-m",
            "hyops.cli",
            "vault",
            "--script",
            str(script),
            "bootstrap",
        ]
    ) != 0:
        print(f"ERR: replacement vault bootstrap failed; backup: {recovery_dir}")
        return INTERNAL_ERROR

    print("Regenerating blueprint credentials.")
    ensure_command = [
        sys.executable,
        "-m",
        "hyops.cli",
        "secrets",
        "ensure",
        "--env",
        str(ns.env),
        *secret_keys,
    ]
    if _run(ensure_command) != 0:
        print(f"ERR: credential regeneration failed; backup: {recovery_dir}")
        return INTERNAL_ERROR

    if _run([sys.executable, "-m", "hyops.cli", "preflight", "--env", str(ns.env)]) != 0:
        print(f"ERR: recovered vault did not pass preflight; backup: {recovery_dir}")
        return INTERNAL_ERROR

    resume = shlex.join(
        [
            "hyops",
            "blueprint",
            "deploy",
            "--env",
            str(ns.env),
            "--ref",
            str(payload["blueprint_ref"]),
            "--execute",
        ]
    )
    print("vault recovery complete")
    print(f"backup: {recovery_dir}")
    print("resume:")
    print(f"  {resume}")
    return 0
