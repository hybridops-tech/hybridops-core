"""
purpose: Initialise HashiCorp Vault runtime inputs and readiness for external secret sync.
Architecture Decision: ADR-N/A
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import webbrowser

from hyops.init.helpers import init_evidence_path, init_run_id, read_kv_file
from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.config import write_template_if_missing
from hyops.runtime.exitcodes import (
    CONFIG_TEMPLATE_WRITTEN,
    OK,
    OPERATOR_ERROR,
    SECRETS_FAILED,
    WRITE_FAILURE,
)
from hyops.runtime.hashicorp_vault import lookup_self
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.readiness import write_marker
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.state import write_json
from hyops.runtime.vault import VaultAuth, has_password_source, merge_set, read_env


_TEMPLATE = """# HashiCorp Vault init configuration (non-secret)
VAULT_ADDR=
VAULT_NAMESPACE=
VAULT_TOKEN_ENV=VAULT_TOKEN
VAULT_ENGINE=kv-v2
VAULT_MAP_FILE=
VAULT_AUTH_METHOD=token
"""


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("hashicorp-vault", help="Initialise HashiCorp Vault runtime inputs.")
    add_init_shared_args(p)
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Write/update env-scoped config from flags/env and continue without a manual config edit step.",
    )
    p.add_argument("--vault-addr", default=None, help="Override HashiCorp Vault address.")
    p.add_argument("--vault-namespace", default=None, help="Override Vault namespace.")
    p.add_argument("--vault-token-env", default=None, help="Override Vault token env var name.")
    p.add_argument("--vault-engine", choices=["kv-v1", "kv-v2"], default=None, help="Override KV engine mode.")
    p.add_argument("--map-file", default=None, help="Override Vault secret map file path.")
    p.add_argument("--auth-method", choices=["token"], default=None, help="Vault auth method (currently token only).")
    p.add_argument("--token", default=None, help="Explicit Vault token for validation/bootstrap.")
    p.add_argument(
        "--persist-token",
        action="store_true",
        help="Persist the validated token into the runtime vault cache under the configured token env key.",
    )
    p.set_defaults(_handler=run)


def _bootstrap_value(*candidates: str | None, default: str = "") -> str:
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return str(default)


def _render_config(
    *,
    vault_addr: str,
    vault_namespace: str,
    token_env: str,
    vault_engine: str,
    map_file: str,
    auth_method: str,
) -> str:
    return (
        "# HashiCorp Vault init configuration (non-secret)\n"
        f"VAULT_ADDR={vault_addr}\n"
        f"VAULT_NAMESPACE={vault_namespace}\n"
        f"VAULT_TOKEN_ENV={token_env}\n"
        f"VAULT_ENGINE={vault_engine}\n"
        f"VAULT_MAP_FILE={map_file}\n"
        f"VAULT_AUTH_METHOD={auth_method}\n"
    )


def _require_tty() -> bool:
    try:
        return bool(os.isatty(0) and os.isatty(1))
    except Exception:
        return False


def _vault_ui_url(vault_addr: str) -> str:
    return str(vault_addr or "").strip().rstrip("/") + "/ui/"


def run(ns) -> int:
    target = "hashicorp-vault"
    run_id = init_run_id("init-hashicorp-vault")

    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    ensure_layout(paths)

    evidence_dir = init_evidence_path(
        root=paths.root,
        out_dir=getattr(ns, "out_dir", None),
        target=target,
        run_id=run_id,
    )

    config_path = (
        Path(ns.config).expanduser().resolve()
        if getattr(ns, "config", None)
        else (paths.config_dir / "hashicorp-vault.conf")
    )
    vault_file = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )
    readiness_file = paths.meta_dir / f"{target}.ready.json"

    try:
        stamp_runtime(
            paths.root,
            command="init",
            target=target,
            run_id=run_id,
            evidence_dir=evidence_dir,
            extra={
                "config": str(config_path),
                "vault": str(vault_file),
                "readiness": str(readiness_file),
                "out_dir": str(getattr(ns, "out_dir", "") or ""),
                "mode": {
                    "non_interactive": bool(getattr(ns, "non_interactive", False)),
                    "dry_run": bool(getattr(ns, "dry_run", False)),
                    "force": bool(getattr(ns, "force", False)),
                    "persist_token": bool(getattr(ns, "persist_token", False)),
                },
            },
        )
    except Exception:
        pass

    template_written = write_template_if_missing(config_path, _TEMPLATE)
    if template_written and not bool(getattr(ns, "bootstrap", False)):
        write_json(
            evidence_dir / "meta.json",
            {
                "target": target,
                "run_id": run_id,
                "status": "needs_config",
                "paths": {
                    "root": str(paths.root),
                    "config": str(config_path),
                    "vault": str(vault_file),
                    "readiness": str(readiness_file),
                    "evidence_dir": str(evidence_dir),
                },
            },
        )
        print(f"wrote config template: {config_path}")
        env_name = str(getattr(ns, "env", "") or "").strip()
        cmd = f"hyops init {target}"
        if env_name:
            cmd = f"{cmd} --env {env_name}"
        print(f"edit the file and re-run: {cmd}")
        return CONFIG_TEMPLATE_WRITTEN

    if bool(getattr(ns, "bootstrap", False)):
        bootstrap_addr = _bootstrap_value(
            getattr(ns, "vault_addr", None),
            os.environ.get("VAULT_ADDR"),
        )
        if not bootstrap_addr:
            print("ERR: --bootstrap requires --vault-addr or VAULT_ADDR.")
            return OPERATOR_ERROR
        bootstrap_namespace = _bootstrap_value(
            getattr(ns, "vault_namespace", None),
            os.environ.get("VAULT_NAMESPACE"),
        )
        bootstrap_token_env = _bootstrap_value(
            getattr(ns, "vault_token_env", None),
            os.environ.get("VAULT_TOKEN_ENV"),
            default="VAULT_TOKEN",
        )
        bootstrap_engine = _bootstrap_value(
            getattr(ns, "vault_engine", None),
            os.environ.get("VAULT_ENGINE"),
            default="kv-v2",
        ).lower()
        bootstrap_map_file = _bootstrap_value(
            getattr(ns, "map_file", None),
            os.environ.get("HYOPS_HASHICORP_VAULT_MAP_FILE"),
        )
        bootstrap_auth_method = _bootstrap_value(
            getattr(ns, "auth_method", None),
            os.environ.get("VAULT_AUTH_METHOD"),
            default="token",
        ).lower()
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                _render_config(
                    vault_addr=bootstrap_addr,
                    vault_namespace=bootstrap_namespace,
                    token_env=bootstrap_token_env,
                    vault_engine=bootstrap_engine,
                    map_file=bootstrap_map_file,
                    auth_method=bootstrap_auth_method,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"ERR: failed to write bootstrap config {config_path}: {exc}")
            return WRITE_FAILURE
        if template_written:
            print(f"bootstrapped config: {config_path}")
        elif bool(getattr(ns, "force", False)):
            print(f"rewrote config from bootstrap inputs: {config_path}")

    cfg = read_kv_file(config_path)
    vault_addr = (
        getattr(ns, "vault_addr", None)
        or os.environ.get("VAULT_ADDR")
        or cfg.get("VAULT_ADDR")
        or ""
    ).strip()
    vault_namespace = (
        getattr(ns, "vault_namespace", None)
        or os.environ.get("VAULT_NAMESPACE")
        or cfg.get("VAULT_NAMESPACE")
        or ""
    ).strip()
    token_env = (
        getattr(ns, "vault_token_env", None)
        or cfg.get("VAULT_TOKEN_ENV")
        or "VAULT_TOKEN"
    ).strip() or "VAULT_TOKEN"
    vault_engine = (
        getattr(ns, "vault_engine", None)
        or cfg.get("VAULT_ENGINE")
        or "kv-v2"
    ).strip().lower() or "kv-v2"
    map_file = (
        getattr(ns, "map_file", None)
        or cfg.get("VAULT_MAP_FILE")
        or ""
    ).strip()
    auth_method = (
        getattr(ns, "auth_method", None)
        or cfg.get("VAULT_AUTH_METHOD")
        or "token"
    ).strip().lower() or "token"

    if auth_method != "token":
        print("ERR: only token auth is supported today for hashicorp-vault init")
        return OPERATOR_ERROR
    if not vault_addr:
        print(f"ERR: VAULT_ADDR is required in {config_path}")
        return OPERATOR_ERROR

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    token = str(getattr(ns, "token", None) or os.environ.get(token_env) or "").strip()
    if not token and vault_file.exists() and has_password_source(auth):
        try:
            token = str(read_env(vault_file, auth).get(token_env) or "").strip()
        except Exception:
            token = ""

    write_json(
        evidence_dir / "meta.json",
        {
            "target": target,
            "run_id": run_id,
            "mode": {
                "non_interactive": bool(getattr(ns, "non_interactive", False)),
                "dry_run": bool(getattr(ns, "dry_run", False)),
                "persist_token": bool(getattr(ns, "persist_token", False)),
            },
            "paths": {
                "root": str(paths.root),
                "config": str(config_path),
                "vault": str(vault_file),
                "readiness": str(readiness_file),
                "evidence_dir": str(evidence_dir),
            },
            "inputs": {
                "vault_addr": vault_addr,
                "vault_namespace": vault_namespace,
                "vault_token_env": token_env,
                "vault_engine": vault_engine,
                "vault_map_file": map_file,
                "auth_method": auth_method,
                "token_present": bool(token),
            },
        },
    )

    if getattr(ns, "dry_run", False):
        print("dry-run: would validate Vault token, optionally persist token, and write readiness")
        print(f"run record: {evidence_dir}")
        return OK

    if not token:
        if bool(getattr(ns, "with_cli_login", False)) and not bool(getattr(ns, "non_interactive", False)):
            if not _require_tty():
                print("ERR: interactive Vault login assistance requires a TTY")
                return OPERATOR_ERROR
            ui_url = _vault_ui_url(vault_addr)
            opened = False
            try:
                opened = bool(webbrowser.open(ui_url, new=2))
            except Exception:
                opened = False
            if opened:
                print(f"opened Vault UI: {ui_url}")
            else:
                print(f"open Vault UI in a browser and complete login: {ui_url}")
            print("paste a Vault token with auth/token/lookup-self access to continue.")
            try:
                token = str(getpass.getpass(f"{token_env}: ")).strip()
            except (EOFError, KeyboardInterrupt):
                token = ""
        if not token:
            print(
                f"ERR: Vault token not available. Set {token_env} in shell env, pass --token, "
                "use --with-cli-login for browser-assisted login, or persist it into the runtime vault cache."
            )
            return OPERATOR_ERROR

    try:
        token_info = lookup_self(vault_addr=vault_addr, token=token, namespace=vault_namespace)
    except Exception as exc:
        print(f"ERR: HashiCorp Vault validation failed: {exc}")
        print(f"run record: {evidence_dir}")
        return SECRETS_FAILED

    if getattr(ns, "persist_token", False):
        try:
            merge_set(vault_file, auth, {token_env: token})
        except Exception as exc:
            print(f"ERR: failed to persist token into runtime vault {vault_file}: {exc}")
            return SECRETS_FAILED

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
                    "vault": str(vault_file),
                    "evidence_dir": str(evidence_dir),
                },
                "context": {
                    "vault_addr": vault_addr,
                    "vault_namespace": vault_namespace,
                    "vault_token_env": token_env,
                    "vault_engine": vault_engine,
                    "vault_map_file": map_file,
                    "auth_method": auth_method,
                    "persisted_token": bool(getattr(ns, "persist_token", False)),
                    "token_accessor": str(token_info.get("data", {}).get("accessor") or ""),
                },
            },
        )
    except Exception:
        print("ERR: failed to write readiness marker")
        return WRITE_FAILURE

    print(f"target={target} status=ready run_id={run_id}")
    print(f"run record: {evidence_dir}")
    print(f"readiness: {marker}")
    print(f"config: {config_path}")
    return OK


__all__ = ["add_subparser"]
