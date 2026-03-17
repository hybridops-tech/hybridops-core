"""
purpose: Initialise Hetzner target runtime inputs (HCLOUD token) and readiness.
Architecture Decision: ADR-N/A
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import stat
from pathlib import Path
import sys

from hyops.runtime.config import write_template_if_missing
from hyops.runtime.exitcodes import (
    CONFIG_TEMPLATE_WRITTEN,
    OK,
    OPERATOR_ERROR,
    TARGET_EXEC_FAILURE,
    VAULT_FAILURE,
    WRITE_FAILURE,
)
from hyops.init.helpers import init_evidence_path, init_run_id, read_kv_file
from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.proc import run_capture
from hyops.runtime.readiness import write_marker
from hyops.runtime.state import write_json
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.vault import VaultAuth, has_password_source, merge_set, read_env


_TEMPLATE = """# Hetzner init configuration (non-secret)
#
# Token handling:
#   - Recommended: store HCLOUD_TOKEN in runtime vault:
#       hyops secrets set --env <env> --from-env HCLOUD_TOKEN
#   - Or run `hyops init hetzner` interactively; when a vault password source
#     exists, HyOps will best-effort persist HCLOUD_TOKEN into the runtime vault.
#
HCLOUD_API=https://api.hetzner.cloud
HCLOUD_TFVARS_OUT=
"""


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("hetzner", help="Initialise Hetzner runtime inputs and readiness.")

    add_init_shared_args(p)

    p.add_argument("--api", default=None, help="Override HCLOUD_API.")
    p.add_argument("--token", default=None, help="Override HCLOUD_TOKEN (discouraged; prefer env/vault).")
    p.add_argument("--tfvars-out", default=None, help="Override credentials tfvars output path.")
    p.add_argument(
        "--ssh-public-key",
        default=None,
        help="Override or persist a non-secret SSH public key into Hetzner init readiness.",
    )
    # Backwards-compatible alias.
    p.add_argument("--credentials-out", default=None, help=argparse.SUPPRESS)
    p.set_defaults(_handler=run)


def _has_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _prompt_hcloud_token(*, reason: str = "missing") -> str:
    if not _has_tty():
        return ""
    if reason == "invalid":
        print("Hetzner token invalid. Enter replacement (hidden) or Ctrl+C.")
    else:
        print("HCLOUD_TOKEN not found. Enter token (hidden):")
    try:
        value = getpass.getpass("HCLOUD_TOKEN: ")
    except (EOFError, KeyboardInterrupt):
        print("")
        return ""
    return str(value or "").strip()


def _validate_hcloud_token(*, evidence_dir: Path, api_endpoint: str, token: str) -> bool:
    # IMPORTANT: Do not put the token on the command line, because evidence
    # persists argv. Pass it via env and reference it inside the shell.
    env = os.environ.copy()
    env.update({"HCLOUD_TOKEN": token, "HCLOUD_API": api_endpoint})
    r = run_capture(
        [
            "/bin/bash",
            "-lc",
            'curl -fsS -o /dev/null -H "Authorization: Bearer ${HCLOUD_TOKEN}" "${HCLOUD_API}/v1/servers"',
        ],
        evidence_dir=evidence_dir,
        label="hcloud_token_check",
        env=env,
        timeout_s=20,
        redact=True,
    )
    return r.rc == 0


def _read_first_pubkey() -> str:
    home = Path.home()
    for p in (home / ".ssh" / "id_ed25519.pub", home / ".ssh" / "id_rsa.pub"):
        try:
            if p.exists():
                v = p.read_text(encoding="utf-8").strip()
                if v:
                    return v
        except Exception:
            continue
    return ""


def run(ns) -> int:
    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    ensure_layout(paths)

    target = "hetzner"
    run_id = init_run_id("init-hetzner")

    evidence_dir = init_evidence_path(
        root=paths.root,
        out_dir=getattr(ns, "out_dir", None),
        target=target,
        run_id=run_id,
    )

    config_path = Path(ns.config).expanduser().resolve() if getattr(ns, "config", None) else (paths.config_dir / "hetzner.conf")
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    readiness_file = paths.meta_dir / f"{target}.ready.json"

    tfvars_out_default = str(paths.credentials_dir / "hetzner.credentials.tfvars")
    tfvars_out_raw = getattr(ns, "tfvars_out", None) or getattr(ns, "credentials_out", None) or tfvars_out_default
    tfvars_out = Path(str(tfvars_out_raw)).expanduser().resolve()

    try:
        stamp_runtime(
            paths.root,
            command="init",
            target=target,
            run_id=run_id,
            evidence_dir=evidence_dir,
            extra={
                "config": str(config_path),
                "vault": str(vault_path),
                "tfvars_out": str(tfvars_out),
                "readiness": str(readiness_file),
                "out_dir": str(getattr(ns, "out_dir", "") or ""),
                "mode": {
                    "dry_run": bool(getattr(ns, "dry_run", False)),
                    "non_interactive": bool(getattr(ns, "non_interactive", False)),
                    "force": bool(getattr(ns, "force", False)),
                },
            },
        )
    except Exception:
        pass

    if write_template_if_missing(config_path, _TEMPLATE):
        write_json(
            evidence_dir / "meta.json",
            {
                "target": target,
                "run_id": run_id,
                "status": "needs_config",
                "paths": {
                    "runtime_root": str(paths.root),
                    "config": str(config_path),
                    "vault": str(vault_path),
                    "tfvars_out": str(tfvars_out),
                    "readiness": str(readiness_file),
                    "evidence_dir": str(evidence_dir),
                },
            },
        )
        print(f"wrote config template: {config_path}")
        print("edit the file and re-run: hyops init hetzner")
        return CONFIG_TEMPLATE_WRITTEN

    cfg = read_kv_file(config_path)

    api_endpoint = (
        getattr(ns, "api", None)
        or os.environ.get("HCLOUD_API")
        or cfg.get("HCLOUD_API")
        or cfg.get("HCLOUD_ENDPOINT")
        or "https://api.hetzner.cloud"
    ).strip()

    tfvars_out_raw = (
        getattr(ns, "tfvars_out", None)
        or getattr(ns, "credentials_out", None)
        or os.environ.get("HCLOUD_TFVARS_OUT")
        or cfg.get("HCLOUD_TFVARS_OUT")
        or tfvars_out_default
    )
    tfvars_out = Path(str(tfvars_out_raw)).expanduser().resolve()
    ssh_public_key = (
        getattr(ns, "ssh_public_key", None)
        or os.environ.get("HCLOUD_SSH_PUBLIC_KEY")
        or cfg.get("HCLOUD_SSH_PUBLIC_KEY")
        or _read_first_pubkey()
        or ""
    ).strip()

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )

    has_vault_password = has_password_source(auth)
    vault_env: dict[str, str] = {}

    if vault_path.exists() and has_vault_password:
        if not shutil.which("ansible-vault"):
            print("ERR: missing command: ansible-vault")
            return OPERATOR_ERROR
        try:
            vault_env = read_env(vault_path, auth)
        except Exception as e:
            if bool(getattr(ns, "non_interactive", False)):
                print(f"ERR: vault decrypt failed: {e}")
                return VAULT_FAILURE
            vault_env = {}

    token = (getattr(ns, "token", None) or "").strip()
    token_source = "missing"
    if token:
        token_source = "cli"
    else:
        token = (os.environ.get("HCLOUD_TOKEN") or "").strip()
        if token:
            token_source = "env"
        else:
            token = (vault_env.get("HCLOUD_TOKEN") or "").strip()
            if token:
                token_source = "vault"
            else:
                # Backwards compatibility only: avoid encouraging secrets-in-config.
                token = (cfg.get("HCLOUD_TOKEN") or "").strip()
                if token:
                    token_source = "config"
                    print(f"WARN: found HCLOUD_TOKEN in config file {config_path}; move it to vault or env")

    if not token and not bool(getattr(ns, "non_interactive", False)):
        prompted = _prompt_hcloud_token(reason="missing")
        if prompted:
            token = prompted
            token_source = "prompt"

    if not token:
        env_name = str(getattr(ns, "env", "") or "").strip() or "<env>"
        print("ERR: HCLOUD_TOKEN is required (Hetzner API token)")
        print("Provide it via one of:")
        print("  - shell env: export HCLOUD_TOKEN=... (then re-run)")
        print("  - interactive prompt: hyops init hetzner")
        print("  - runtime vault (recommended):")
        print(f"      hyops secrets set --env {env_name} --from-env HCLOUD_TOKEN")
        print("    or")
        print(f"      hyops secrets set --env {env_name} HCLOUD_TOKEN=...")
        if not _has_tty() and not bool(getattr(ns, "non_interactive", False)):
            print("hint: no interactive TTY detected; use env/vault/--token")
        if bool(getattr(ns, "non_interactive", False)):
            return VAULT_FAILURE
        return OPERATOR_ERROR

    token_persisted = False

    write_json(
        evidence_dir / "meta.json",
        {
            "target": target,
            "run_id": run_id,
            "mode": {
                "non_interactive": bool(getattr(ns, "non_interactive", False)),
                "dry_run": bool(getattr(ns, "dry_run", False)),
                "force": bool(getattr(ns, "force", False)),
            },
            "paths": {
                "runtime_root": str(paths.root),
                "config": str(config_path),
                "vault": str(vault_path),
                "tfvars_out": str(tfvars_out),
                "readiness": str(readiness_file),
                "evidence_dir": str(evidence_dir),
            },
            "inputs": {
                "api": api_endpoint,
                "token_source": token_source,
                "token_persisted": token_persisted,
                "ssh_public_key_present": bool(ssh_public_key),
            },
        },
    )

    if getattr(ns, "dry_run", False):
        print("dry-run: would validate token, write tfvars, and write readiness")
        print(f"run record: {evidence_dir}")
        return OK

    if not shutil.which("curl"):
        print("ERR: missing command: curl")
        return OPERATOR_ERROR

    validated = _validate_hcloud_token(evidence_dir=evidence_dir, api_endpoint=api_endpoint, token=token)
    if not validated and not bool(getattr(ns, "non_interactive", False)) and _has_tty():
        replacement = _prompt_hcloud_token(reason="invalid")
        if replacement:
            token = replacement
            token_source = "prompt"
            validated = _validate_hcloud_token(evidence_dir=evidence_dir, api_endpoint=api_endpoint, token=token)
    if not validated:
        print("ERR: Hetzner token validation failed; see evidence")
        print(f"run record: {evidence_dir}")
        return TARGET_EXEC_FAILURE

    if tfvars_out.exists() and not bool(getattr(ns, "force", False)):
        print(f"ERR: credentials file already exists (use --force to overwrite): {tfvars_out}")
        return OPERATOR_ERROR

    try:
        tfvars_out.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            "# <sensitive> Do not commit.\n"
            "# purpose: Hetzner runtime credentials for Terraform stacks.\n"
            "# </sensitive>\n\n"
            f'hcloud_token = "{token}"\n'
            f'hcloud_api   = "{api_endpoint}"\n'
        )
        tfvars_out.write_text(payload, encoding="utf-8")
        os.chmod(tfvars_out, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        print("ERR: failed to write hetzner credentials tfvars")
        return WRITE_FAILURE

    if token_source == "prompt":
        if has_vault_password:
            if not shutil.which("ansible-vault"):
                print("WARN: ansible-vault not found; HCLOUD_TOKEN used for this run only")
            else:
                try:
                    merge_set(vault_path, auth, {"HCLOUD_TOKEN": token})
                    token_persisted = True
                    print(f"stored HCLOUD_TOKEN in runtime vault: {vault_path}")
                except Exception as e:
                    print(f"WARN: failed to persist HCLOUD_TOKEN in vault: {e}")
                    print("hint: run `hyops secrets set --env <env> --from-env HCLOUD_TOKEN` later")
        else:
            print("note: HCLOUD_TOKEN used for this run only (no vault password source configured)")
            print("hint: configure vault password source to auto-persist bootstrap credentials")

    try:
        marker = write_marker(
            paths.meta_dir,
            target,
            {
                "target": target,
                "status": "ready",
                "run_id": run_id,
                "paths": {
                    "config": str(config_path),
                    "credentials": str(tfvars_out),
                    "vault": str(vault_path),
                    "evidence_dir": str(evidence_dir),
                },
                "context": {
                    "api": api_endpoint,
                    "ssh_public_key": ssh_public_key,
                },
            },
        )
    except Exception:
        print("ERR: failed to write readiness marker")
        return WRITE_FAILURE

    print(f"target={target} status=ready run_id={run_id}")
    print(f"run record: {evidence_dir}")
    print(f"readiness: {marker}")
    print(f"credentials: {tfvars_out}")
    if not ssh_public_key:
        print("WARN: no SSH public key discovered for Hetzner runtime.")
        print("hint: re-run with --ssh-public-key, set HCLOUD_SSH_PUBLIC_KEY in config/env, or ensure ~/.ssh/id_ed25519.pub exists.")
        print("hint: org/hetzner/shared-control-host with ssh_keys_from_init=true will fail until a key is present in hetzner.ready.json")

    return OK


__all__ = ["add_subparser"]
