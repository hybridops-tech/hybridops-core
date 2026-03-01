"""
purpose: Init Terraform Cloud token and render Terraform CLI credentials.
Architecture Decision: ADR-N/A
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from hyops.runtime.config import write_template_if_missing
from hyops.runtime.exitcodes import (
    CONFIG_TEMPLATE_WRITTEN,
    OK,
    OPERATOR_ERROR,
    TARGET_EXEC_FAILURE,
    VAULT_FAILURE,
    WRITE_FAILURE,
)
from hyops.init.helpers import init_evidence_path, init_run_id
from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.proc import run_capture, run_capture_sensitive
from hyops.runtime.readiness import write_marker
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.terraform_cloud import read_tfrc_token, resolve_config, write_tfrc_token
from hyops.runtime.vault import VaultAuth, has_password_source, merge_set, read_env


_TEMPLATE = """# Terraform Cloud init configuration (non-secret)
TFC_HOST=app.terraform.io
TFC_ORG=
WORKSPACE_PREFIX=hybridops
TFC_CREDENTIALS_FILE=~/.terraform.d/credentials.tfrc.json
"""


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("terraform-cloud", help="Initialise Terraform Cloud credentials.")

    add_init_shared_args(p)
    p.add_argument("--tfc-host", default=None, help="Override Terraform Cloud host.")
    p.add_argument("--tfc-org", default=None, help="Override Terraform Cloud organisation.")
    p.add_argument("--workspace-prefix", default=None, help="Override workspace prefix.")
    p.add_argument("--credentials-file", default=None, help="Override Terraform CLI credentials file path.")
    p.set_defaults(_handler=run)


def run(ns) -> int:
    target = "terraform-cloud"
    run_id = init_run_id("init-terraform-cloud")

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
        else (paths.config_dir / "terraform-cloud.conf")
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
                },
            },
        )
    except Exception:
        pass

    if write_template_if_missing(config_path, _TEMPLATE):
        _write_json(
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
                    "evidence": str(evidence_dir),
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

    overrides: dict[str, str] = {}
    if ns.tfc_host:
        overrides["TFC_HOST"] = str(ns.tfc_host)
    if ns.tfc_org:
        overrides["TFC_ORG"] = str(ns.tfc_org)
    if ns.workspace_prefix:
        overrides["WORKSPACE_PREFIX"] = str(ns.workspace_prefix)
    if ns.credentials_file:
        overrides["TFC_CREDENTIALS_FILE"] = str(ns.credentials_file)

    tfc = resolve_config(config_path=config_path, overrides=overrides)
    tfc_host = tfc.host
    tfc_org = tfc.org
    workspace_prefix = tfc.workspace_prefix
    credentials_file = tfc.credentials_file

    if not tfc_org:
        print(f"ERR: TFC_ORG is required in {config_path}")
        return OPERATOR_ERROR

    for cmd in ("terraform", "curl"):
        if not _has_cmd(cmd):
            print(f"ERR: missing command: {cmd}")
            return OPERATOR_ERROR

    need_vault = bool(
        vault_file.exists()
        or getattr(ns, "non_interactive", False)
        or getattr(ns, "vault_password_file", None)
        or getattr(ns, "vault_password_command", None)
    )
    if need_vault and not _has_cmd("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        return OPERATOR_ERROR

    _write_json(
        evidence_dir / "meta.json",
        {
            "target": target,
            "run_id": run_id,
            "mode": {
                "non_interactive": bool(getattr(ns, "non_interactive", False)),
                "dry_run": bool(getattr(ns, "dry_run", False)),
            },
            "tfc": {"host": tfc_host, "org": tfc_org, "workspace_prefix": workspace_prefix},
            "paths": {
                "root": str(paths.root),
                "config": str(config_path),
                "vault": str(vault_file),
                "credentials_file": str(credentials_file),
                "readiness": str(readiness_file),
                "evidence": str(evidence_dir),
            },
        },
    )

    if ns.dry_run:
        print("dry-run: would validate token, write credentials, and write readiness")
        print(f"evidence: {evidence_dir}")
        return OK

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    has_vault_password = has_password_source(auth)

    explicit_vault_auth = bool(
        getattr(ns, "vault_password_file", None)
        or getattr(ns, "vault_password_command", None)
    )
    persist_to_vault = bool(vault_file.exists() or explicit_vault_auth)

    token: str | None = None
    vault_env: dict[str, str] = {}

    if vault_file.exists() and has_vault_password:
        try:
            vault_env = read_env(vault_file, auth)
        except Exception as e:
            if ns.non_interactive:
                print(f"ERR: vault decrypt failed: {e}")
                return VAULT_FAILURE
            vault_env = {}

    candidate = (vault_env.get("TFC_TOKEN") or "").strip()
    if candidate and _validate_token(tfc_host, tfc_org, candidate, evidence_dir):
        token = candidate

    if not token:
        candidate = read_tfrc_token(credentials_file, tfc_host)
        if candidate and _validate_token(tfc_host, tfc_org, candidate, evidence_dir):
            token = candidate

    if not token:
        if ns.non_interactive:
            print("ERR: non-interactive mode requires a valid TFC_TOKEN in the vault")
            return VAULT_FAILURE

        if not bool(getattr(ns, "with_cli_login", False)):
            print("ERR: Terraform Cloud token not available.")
            print("Provide TFC_TOKEN in the vault, or run: terraform login " + tfc_host)
            print("Then re-run: hyops init terraform-cloud --with-cli-login")
            env_name = str(getattr(ns, "env", "") or "").strip()
            if env_name:
                print(f"(hint) include env: hyops init terraform-cloud --env {env_name} --with-cli-login")
            return OPERATOR_ERROR

        env_name = str(getattr(ns, "env", "") or "").strip()
        if env_name:
            print(f"target env: {env_name}")

        if not _require_tty():
            print("ERR: terraform login requires a TTY")
            return OPERATOR_ERROR

        r = run_capture(["terraform", "login", tfc_host], evidence_dir=evidence_dir, label="terraform_login", redact=True)
        if r.rc != 0:
            print("ERR: terraform login failed; see evidence")
            return TARGET_EXEC_FAILURE

        new_token = read_tfrc_token(credentials_file, tfc_host)
        if not new_token:
            print(f"ERR: token not found in {credentials_file} after terraform login")
            return TARGET_EXEC_FAILURE

        if not _validate_token(tfc_host, tfc_org, new_token, evidence_dir):
            print("ERR: token failed validation")
            return TARGET_EXEC_FAILURE

        token = new_token

    if persist_to_vault and has_vault_password and token:
        try:
            vault_file.parent.mkdir(parents=True, exist_ok=True)
            merge_set(vault_file, auth, {"TFC_TOKEN": token})
        except Exception as e:
            if explicit_vault_auth:
                print(f"ERR: vault persistence failed: {e}")
                return VAULT_FAILURE
            print(f"WARN: vault persistence skipped: {e}")

    try:
        write_tfrc_token(credentials_file, tfc_host, token)
    except Exception:
        print("ERR: failed to write Terraform CLI credentials file")
        return WRITE_FAILURE

    marker_paths: dict[str, str] = {
        "config": str(config_path),
        "credentials": str(credentials_file),
        "evidence": str(evidence_dir),
    }
    if vault_file.exists():
        marker_paths["vault"] = str(vault_file)

    try:
        write_marker(
            paths.meta_dir,
            target,
            {
                "target": target,
                "status": "ready",
                "run_id": run_id,
                "paths": marker_paths,
            },
        )
    except Exception:
        print("ERR: failed to write readiness marker")
        return WRITE_FAILURE

    print(f"target={target} status=ready run_id={run_id}")
    print(f"evidence: {evidence_dir}")
    print(f"readiness: {readiness_file}")
    print(f"credentials: {credentials_file}")

    if bool(getattr(ns, "logout_after", False)):
        # Best-effort cleanup; do not fail init if logout fails.
        run_capture(
            ["terraform", "logout", tfc_host],
            evidence_dir=evidence_dir,
            label="terraform_logout",
            redact=True,
        )

    return OK


def _has_cmd(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


def _write_json(path: Path, payload: object) -> None:
    from hyops.runtime.state import write_json

    write_json(path, payload)


def _validate_token(host: str, org: str, token: str, evidence_dir: Path) -> bool:
    url = f"https://{host}/api/v2/organizations/{org}"

    env = os.environ.copy()
    env.update({"TFC_TOKEN": token})

    r = run_capture_sensitive(
        [
            "/bin/bash",
            "-lc",
            "curl -s -o /dev/null -w '%{http_code}' "
            "-H 'Authorization: Bearer '$TFC_TOKEN "
            "-H 'Content-Type: application/vnd.api+json' "
            + url,
        ],
        evidence_dir=evidence_dir,
        label="tfc_validate",
        env=env,
    )

    if r.rc != 0:
        return False

    return (r.stdout or "").strip() == "200"


def _require_tty() -> bool:
    return os.isatty(0) and os.isatty(1)
