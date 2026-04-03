"""
purpose: Initialise AWS target runtime inputs (region/profile/credentials tfvars) and readiness.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
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
from hyops.init.helpers import init_evidence_path, init_run_id, read_kv_file
from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.proc import run_capture, run_capture_interactive
from hyops.runtime.readiness import write_marker
from hyops.runtime.state import write_json
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.vault import VaultAuth, has_password_source, read_env


_TEMPLATE = """# AWS init configuration (non-secret)
#
# Credential handling (recommended):
#   - export AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in shell and run:
#       hyops init aws --env <env>
#   - or store them in runtime vault:
#       hyops secrets set --env <env> --from-env AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
#
AWS_REGION=us-east-1
AWS_PROFILE=
AWS_TFVARS_OUT=
"""


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("aws", help="Initialise AWS runtime inputs and readiness.")

    add_init_shared_args(p)

    p.add_argument("--region", default=None, help="Override AWS_REGION.")
    p.add_argument("--profile", default=None, help="Override AWS_PROFILE (optional).")
    p.add_argument("--access-key-id", default=None, help="Override AWS_ACCESS_KEY_ID (discouraged; prefer env/vault).")
    p.add_argument("--secret-access-key", default=None, help="Override AWS_SECRET_ACCESS_KEY (discouraged; prefer env/vault).")
    p.add_argument("--session-token", default=None, help="Override AWS_SESSION_TOKEN (optional; discouraged; prefer env/vault).")
    p.add_argument("--tfvars-out", default=None, help="Override credentials tfvars output path.")
    # Backwards-compatible alias.
    p.add_argument("--credentials-out", default=None, help=argparse.SUPPRESS)
    p.set_defaults(_handler=run)


def run(ns) -> int:
    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    ensure_layout(paths)

    target = "aws"
    run_id = init_run_id("init-aws")

    evidence_dir = init_evidence_path(
        root=paths.root,
        out_dir=getattr(ns, "out_dir", None),
        target=target,
        run_id=run_id,
    )

    config_path = Path(ns.config).expanduser().resolve() if getattr(ns, "config", None) else (paths.config_dir / "aws.conf")
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    readiness_file = paths.meta_dir / f"{target}.ready.json"

    tfvars_out_default = str(paths.credentials_dir / "aws.credentials.tfvars")
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
        print("edit the file and re-run: hyops init aws")
        return CONFIG_TEMPLATE_WRITTEN

    cfg = read_kv_file(config_path)

    region = (
        getattr(ns, "region", None)
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or cfg.get("AWS_REGION")
        or "us-east-1"
    ).strip()

    profile = (
        getattr(ns, "profile", None)
        or os.environ.get("AWS_PROFILE")
        or cfg.get("AWS_PROFILE")
        or ""
    ).strip()

    tfvars_out_raw = (
        getattr(ns, "tfvars_out", None)
        or getattr(ns, "credentials_out", None)
        or os.environ.get("AWS_TFVARS_OUT")
        or cfg.get("AWS_TFVARS_OUT")
        or tfvars_out_default
    )
    tfvars_out = Path(str(tfvars_out_raw)).expanduser().resolve()

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )

    has_vault_password = has_password_source(auth)
    explicit_vault_source = bool(
        getattr(ns, "vault_file", None)
        or getattr(ns, "vault_password_file", None)
        or getattr(ns, "vault_password_command", None)
    )

    access_key_id = (getattr(ns, "access_key_id", None) or "").strip()
    if not access_key_id:
        access_key_id = (os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()

    secret_access_key = (getattr(ns, "secret_access_key", None) or "").strip()
    if not secret_access_key:
        secret_access_key = (os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()

    session_token = (getattr(ns, "session_token", None) or "").strip()
    if not session_token:
        session_token = (os.environ.get("AWS_SESSION_TOKEN") or "").strip()

    vault_env: dict[str, str] = {}
    need_vault_lookup = (not access_key_id) or (not secret_access_key) or (not session_token)

    if need_vault_lookup and vault_path.exists() and has_vault_password:
        if not shutil.which("ansible-vault"):
            print("ERR: missing command: ansible-vault")
            return OPERATOR_ERROR
        try:
            vault_env = read_env(vault_path, auth)
        except Exception as e:
            # Vault is optional for AWS init; only fail hard when the operator
            # explicitly requested vault input in non-interactive mode.
            if explicit_vault_source and bool(getattr(ns, "non_interactive", False)):
                print(f"ERR: vault decrypt failed: {e}")
                return VAULT_FAILURE
            vault_env = {}

        if not access_key_id:
            access_key_id = (vault_env.get("AWS_ACCESS_KEY_ID") or "").strip()
        if not secret_access_key:
            secret_access_key = (vault_env.get("AWS_SECRET_ACCESS_KEY") or "").strip()
        if not session_token:
            session_token = (vault_env.get("AWS_SESSION_TOKEN") or "").strip()

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
                "region": region,
                "profile": profile,
                "has_access_key_id": bool(access_key_id),
                "has_secret_access_key": bool(secret_access_key),
                "has_session_token": bool(session_token),
            },
        },
    )

    if getattr(ns, "dry_run", False):
        print("dry-run: would validate AWS identity, write tfvars, and write readiness")
        print(f"run record: {evidence_dir}")
        return OK

    if not shutil.which("aws"):
        print("ERR: missing command: aws")
        print("hint: install AWS CLI and re-run: hyops init aws")
        return OPERATOR_ERROR

    if tfvars_out.exists() and not bool(getattr(ns, "force", False)):
        print(f"ERR: credentials file already exists (use --force to overwrite): {tfvars_out}")
        return OPERATOR_ERROR

    aws_env = os.environ.copy()
    if region:
        aws_env["AWS_REGION"] = region
        aws_env["AWS_DEFAULT_REGION"] = region
    if profile:
        aws_env["AWS_PROFILE"] = profile
    if access_key_id:
        aws_env["AWS_ACCESS_KEY_ID"] = access_key_id
    if secret_access_key:
        aws_env["AWS_SECRET_ACCESS_KEY"] = secret_access_key
    if session_token:
        aws_env["AWS_SESSION_TOKEN"] = session_token

    r = run_capture(
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        evidence_dir=evidence_dir,
        label="aws_sts_get_caller_identity",
        env=aws_env,
        timeout_s=25,
        redact=True,
    )

    if r.rc != 0:
        if bool(getattr(ns, "with_cli_login", False)) and profile and not bool(getattr(ns, "non_interactive", False)):
            print("starting interactive AWS SSO login; follow the prompts shown below.")
            login = run_capture_interactive(
                ["aws", "sso", "login", "--profile", profile],
                evidence_dir=evidence_dir,
                label="aws_sso_login",
                env=aws_env,
                timeout_s=180,
                redact=True,
            )
            if login.rc == 0:
                r2 = run_capture(
                    ["aws", "sts", "get-caller-identity", "--output", "json"],
                    evidence_dir=evidence_dir,
                    label="aws_sts_get_caller_identity_after_login",
                    env=aws_env,
                    timeout_s=25,
                    redact=True,
                )
                if r2.rc == 0:
                    r = r2

        if r.rc != 0:
            print("ERR: AWS identity validation failed; see evidence")
            print("hint: configure one of:")
            print("  - aws configure sso --profile <name> && aws sso login --profile <name>")
            print("  - export AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY")
            print("  - hyops secrets set --env <env> --from-env AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY")
            print(f"run record: {evidence_dir}")
            return TARGET_EXEC_FAILURE

    try:
        tfvars_out.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# <sensitive> Do not commit.",
            "# purpose: AWS runtime credentials for Terraform stacks.",
            "# </sensitive>",
            "",
            f'aws_region = "{region}"',
        ]
        if profile:
            lines.append(f'aws_profile = "{profile}"')
        if access_key_id:
            lines.append(f'aws_access_key_id = "{access_key_id}"')
        if secret_access_key:
            lines.append(f'aws_secret_access_key = "{secret_access_key}"')
        if session_token:
            lines.append(f'aws_session_token = "{session_token}"')
        lines.append("")
        tfvars_out.write_text("\n".join(lines), encoding="utf-8")
        os.chmod(tfvars_out, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        print("ERR: failed to write aws credentials tfvars")
        return WRITE_FAILURE

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
                    "region": region,
                    "profile": profile,
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

    return OK


__all__ = ["add_subparser"]
