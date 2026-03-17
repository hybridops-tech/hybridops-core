"""Init target: azure.

purpose: Initialise Azure runtime credentials, evidence, and readiness.
Architecture Decision: ADR-N/A (init azure)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from pathlib import Path
import shutil
import stat

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
from hyops.runtime.proc import run_capture, run_capture_interactive, run_capture_sensitive
from hyops.runtime.readiness import write_marker
from hyops.runtime.state import write_json
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.vault import VaultAuth, has_password_source, merge_set, read_env


_SP_NAME_BASE = "sp-hybridops-terraform-bootstrap"


def _default_sp_name(env_name: str) -> str:
    """Default bootstrap SP name.

    Important: Avoid a single shared SP across envs because rotating the secret
    for one env will invalidate the others.
    """

    env_name = (env_name or "").strip()
    return f"{_SP_NAME_BASE}-{env_name}" if env_name else _SP_NAME_BASE


def _template_for_env(env_name: str) -> str:
    sp = _default_sp_name(env_name)
    return (
        "# Azure init configuration (non-secret)\n"
        "AZ_LOCATION=uksouth\n"
        "# IMPORTANT: use a unique AZ_SP_NAME per HyOps env.\n"
        "# Rotating the client secret for one env will break other envs that share the same SP.\n"
        f"AZ_SP_NAME={sp}\n"
        "AZ_SUBSCRIPTION_ID=\n"
        "AZ_TENANT_ID=\n"
        "AZ_TFVARS_OUT=\n"
    )


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser(
        "azure",
        help="Initialise Azure runtime credentials and readiness.",
        epilog=(
            "Notes:\n"
            "  - Shared flags live on `hyops init` (e.g. --root, --out-dir, --config, --vault-*).\n"
            "  - Required non-secret config key: AZ_LOCATION.\n"
            "  - Non-interactive mode requires bootstrap SP secrets in the vault."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    add_init_shared_args(p)

    p.add_argument("--location", default=None, help="Override AZ_LOCATION.")
    p.add_argument("--sp-name", default=None, help="Override AZ_SP_NAME.")
    p.add_argument(
        "--allow-shared-sp",
        action="store_true",
        help="Allow AZ_SP_NAME to be shared across multiple local envs (not recommended).",
    )
    p.add_argument("--subscription-id", default=None, help="Override AZ_SUBSCRIPTION_ID.")
    p.add_argument("--tenant-id", default=None, help="Override AZ_TENANT_ID.")
    p.add_argument("--tfvars-out", default=None, help="Override Azure credentials tfvars output path.")
    p.set_defaults(_handler=run)


def run(ns) -> int:
    target = "azure"
    run_id = init_run_id("init-azure")

    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    ensure_layout(paths)

    env_name = str(getattr(ns, "env", "") or os.environ.get("HYOPS_ENV") or "").strip()
    # Best-effort inference for standard layout: ~/.hybridops/envs/<env>
    if not env_name and paths.root.parent.name == "envs":
        env_name = paths.root.name

    config_path = (
        Path(ns.config).expanduser().resolve()
        if getattr(ns, "config", None)
        else (paths.config_dir / "azure.conf")
    )
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    evidence_dir = init_evidence_path(
        root=paths.root,
        out_dir=getattr(ns, "out_dir", None),
        target=target,
        run_id=run_id,
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
                "vault": str(vault_path),
                "readiness": str(readiness_file),
                "out_dir": str(getattr(ns, "out_dir", "") or ""),
                "mode": {
                    "non_interactive": bool(getattr(ns, "non_interactive", False)),
                    "force": bool(getattr(ns, "force", False)),
                    "dry_run": bool(getattr(ns, "dry_run", False)),
                },
            },
        )
    except Exception:
        pass

    if write_template_if_missing(config_path, _template_for_env(env_name)):
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
                    "readiness": str(readiness_file),
                    "evidence_dir": str(evidence_dir),
                },
            },
        )
        print(f"wrote config template: {config_path}")
        print("edit the file and re-run: hyops init azure")
        return CONFIG_TEMPLATE_WRITTEN

    cfg = read_kv_file(config_path)

    location = ""
    location_source = ""
    if getattr(ns, "location", None):
        location = str(getattr(ns, "location", None) or "").strip()
        location_source = "flag"
    elif os.environ.get("AZ_LOCATION"):
        location = str(os.environ.get("AZ_LOCATION") or "").strip()
        location_source = "env"
    elif cfg.get("AZ_LOCATION"):
        location = str(cfg.get("AZ_LOCATION") or "").strip()
        location_source = "config"
    else:
        location = "uksouth"
        location_source = "default"

    sp_name = ""
    sp_name_source = ""
    if getattr(ns, "sp_name", None):
        sp_name = str(getattr(ns, "sp_name", None) or "").strip()
        sp_name_source = "flag"
    elif os.environ.get("AZ_SP_NAME"):
        sp_name = str(os.environ.get("AZ_SP_NAME") or "").strip()
        sp_name_source = "env"
    elif cfg.get("AZ_SP_NAME"):
        sp_name = str(cfg.get("AZ_SP_NAME") or "").strip()
        sp_name_source = "config"
    else:
        sp_name = _default_sp_name(env_name)
        sp_name_source = "default"

    subscription_id = ""
    subscription_id_source = ""
    if getattr(ns, "subscription_id", None):
        subscription_id = str(getattr(ns, "subscription_id", None) or "").strip()
        subscription_id_source = "flag"
    elif os.environ.get("AZ_SUBSCRIPTION_ID"):
        subscription_id = str(os.environ.get("AZ_SUBSCRIPTION_ID") or "").strip()
        subscription_id_source = "env"
    elif cfg.get("AZ_SUBSCRIPTION_ID"):
        subscription_id = str(cfg.get("AZ_SUBSCRIPTION_ID") or "").strip()
        subscription_id_source = "config"

    tenant_id = ""
    tenant_id_source = ""
    if getattr(ns, "tenant_id", None):
        tenant_id = str(getattr(ns, "tenant_id", None) or "").strip()
        tenant_id_source = "flag"
    elif os.environ.get("AZ_TENANT_ID"):
        tenant_id = str(os.environ.get("AZ_TENANT_ID") or "").strip()
        tenant_id_source = "env"
    elif cfg.get("AZ_TENANT_ID"):
        tenant_id = str(cfg.get("AZ_TENANT_ID") or "").strip()
        tenant_id_source = "config"

    tfvars_out_raw = (
        getattr(ns, "tfvars_out", None)
        or os.environ.get("AZ_TFVARS_OUT")
        or cfg.get("AZ_TFVARS_OUT")
        or str(paths.credentials_dir / "azure.credentials.tfvars")
    )
    tfvars_out = Path(tfvars_out_raw).expanduser().resolve()

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
                "location": location,
                "sp_name": sp_name,
                "subscription_id": subscription_id,
                "tenant_id": tenant_id,
            },
        },
    )

    if not location:
        print(f"ERR: AZ_LOCATION is required in {config_path}")
        return OPERATOR_ERROR

    if getattr(ns, "dry_run", False):
        print("dry-run: would validate/login Azure SP creds, then write tfvars + readiness")
        print(f"run record: {evidence_dir}")
        return OK

    if not _has_cmd("az"):
        print("ERR: missing command: az")
        return OPERATOR_ERROR

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )

    has_vault_password = has_password_source(auth)
    # Even in interactive mode, we may need ansible-vault to persist credentials to the vault.
    need_vault = bool(getattr(ns, "non_interactive", False) or has_vault_password or vault_path.exists())
    if need_vault and not _has_cmd("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        print(f"run record: {evidence_dir}")
        return OPERATOR_ERROR
    vault_env: dict[str, str] = {}

    if getattr(ns, "non_interactive", False):
        if not vault_path.exists():
            print(f"ERR: non-interactive mode requires vault file: {vault_path}")
            return VAULT_FAILURE
        if not has_vault_password:
            print("ERR: non-interactive mode requires --vault-password-file or --vault-password-command")
            return VAULT_FAILURE

    if vault_path.exists() and has_vault_password:
        try:
            vault_env = read_env(vault_path, auth)
        except Exception as e:
            if getattr(ns, "non_interactive", False):
                print(f"ERR: vault decrypt failed: {e}")
                return VAULT_FAILURE
            vault_env = {}

    client_id = (os.environ.get("AZ_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("AZ_CLIENT_SECRET") or "").strip()

    if getattr(ns, "non_interactive", False):
        missing: list[str] = []
        for key in ("AZ_CLIENT_ID", "AZ_CLIENT_SECRET", "AZ_TENANT_ID", "AZ_SUBSCRIPTION_ID"):
            if not (vault_env.get(key) or "").strip():
                missing.append(key)
        if missing:
            print(f"ERR: non-interactive requires vault keys: {', '.join(missing)}")
            return VAULT_FAILURE

        client_id = vault_env["AZ_CLIENT_ID"].strip()
        client_secret = vault_env["AZ_CLIENT_SECRET"].strip()
        tenant_id = vault_env["AZ_TENANT_ID"].strip()
        subscription_id = vault_env["AZ_SUBSCRIPTION_ID"].strip()
    else:
        client_id = client_id or (vault_env.get("AZ_CLIENT_ID") or "").strip()
        client_secret = client_secret or (vault_env.get("AZ_CLIENT_SECRET") or "").strip()
        tenant_id = tenant_id or (vault_env.get("AZ_TENANT_ID") or "").strip()
        subscription_id = subscription_id or (vault_env.get("AZ_SUBSCRIPTION_ID") or "").strip()

    rotated_or_created = False
    roles_ensured = False
    vault_persisted = False

    if getattr(ns, "non_interactive", False):
        ok, detail = _az_login_sp(
            evidence_dir,
            "az_login_sp_non_interactive",
            client_id,
            client_secret,
            tenant_id,
            allow_no_subscriptions=False,
        )
        if not ok:
            if detail:
                print(f"ERR: non-interactive SP login failed: {detail}")
            else:
                print("ERR: non-interactive SP login failed")
            print("hint: check that AZ_CLIENT_ID/AZ_CLIENT_SECRET/AZ_TENANT_ID are correct and not expired.")
            print(f"run record: {evidence_dir}")
            return VAULT_FAILURE
    else:
        has_valid_sp = False
        if client_id and client_secret and tenant_id:
            has_valid_sp, _ = _az_login_sp(
                evidence_dir,
                "az_login_sp_existing",
                client_id,
                client_secret,
                tenant_id,
                allow_no_subscriptions=False,
            )

        if not has_valid_sp:
            if not has_vault_password:
                print("ERR: vault password source required to persist bootstrap SP updates")
                return VAULT_FAILURE

            if not bool(getattr(ns, "with_cli_login", False)):
                print("ERR: Azure CLI login required to bootstrap service principal credentials.")
                print("Option A: run `az login` then re-run with: hyops init azure --with-cli-login")
                print("Option B: pre-seed AZ_CLIENT_ID/AZ_CLIENT_SECRET/AZ_TENANT_ID/AZ_SUBSCRIPTION_ID in the env vault and use --non-interactive")
                return OPERATOR_ERROR

            if not _az_ok(["account", "show", "--output", "none"], evidence_dir, "az_account_show_interactive"):
                print("starting interactive Azure login; follow the prompts shown below.")
                login = run_capture_interactive(
                    ["az", "login", "--only-show-errors"],
                    evidence_dir=evidence_dir,
                    label="az_login_interactive",
                    redact=True,
                )
                if login.rc != 0:
                    print("ERR: az login failed")
                    return TARGET_EXEC_FAILURE

            # Make the active Azure identity explicit before mutating tenant state.
            who = _az_tsv(["account", "show", "--query", "user.name", "-o", "tsv"], evidence_dir, "az_account_user")
            sub_active = _az_tsv(["account", "show", "--query", "id", "-o", "tsv"], evidence_dir, "az_account_sub_active")
            ten_active = _az_tsv(["account", "show", "--query", "tenantId", "-o", "tsv"], evidence_dir, "az_account_tenant_active")
            user_type = _az_tsv(["account", "show", "--query", "user.type", "-o", "tsv"], evidence_dir, "az_account_user_type")
            print(
                f"azure identity: type={user_type or 'unknown'} user={who or 'unknown'} tenant={ten_active or 'unknown'} subscription={sub_active or 'unknown'}"
            )
            if env_name:
                print(f"target env: {env_name}")

            if user_type and user_type.strip().lower() != "user":
                print("ERR: Azure CLI is not logged in as a user (user.type != user).")
                print("interactive bootstrap requires a user identity with directory permissions.")
                print("suggested:")
                print("  az logout")
                print("  az login")
                print("  hyops init azure --env <env> --with-cli-login")
                print("or:")
                print("  pre-seed AZ_CLIENT_ID/AZ_CLIENT_SECRET/AZ_TENANT_ID/AZ_SUBSCRIPTION_ID in the env vault and use --non-interactive")
                print(f"run record: {evidence_dir}")
                return OPERATOR_ERROR

            if os.isatty(0) and os.isatty(1):
                try:
                    answer = input("continue with this Azure identity? [y/N]: ")
                except EOFError:
                    answer = ""
                if str(answer or "").strip().lower() not in ("y", "yes"):
                    print("cancelled. switch identity and re-run.")
                    print("suggested:")
                    print("  az logout")
                    print("  az login")
                    return OPERATOR_ERROR

            if (
                bool(getattr(ns, "with_cli_login", False))
                and bool(getattr(ns, "force", False))
                and os.isatty(0)
                and os.isatty(1)
                and any(src in {"config", "env"} for src in (location_source, sp_name_source, subscription_id_source, tenant_id_source))
            ):
                location, sp_name, subscription_id, tenant_id = _review_detected_azure_defaults_interactive(
                    env_name=env_name,
                    location=location,
                    location_source=location_source,
                    sp_name=sp_name,
                    sp_name_source=sp_name_source,
                    subscription_id=subscription_id,
                    subscription_id_source=subscription_id_source,
                    tenant_id=tenant_id,
                    tenant_id_source=tenant_id_source,
                )
                _upsert_kv_file(
                    config_path,
                    {
                        "AZ_LOCATION": location,
                        "AZ_SP_NAME": sp_name,
                        "AZ_SUBSCRIPTION_ID": subscription_id,
                        "AZ_TENANT_ID": tenant_id,
                    },
                )

            allow_shared_sp = bool(getattr(ns, "allow_shared_sp", False)) or _truthy(os.environ.get("AZ_ALLOW_SHARED_SP"))
            shared_envs = _other_envs_with_same_sp_name(paths, env_name, sp_name)
            if shared_envs:
                print(f"WARNING: AZ_SP_NAME={sp_name} is also configured for env(s): {', '.join(shared_envs)}")
                print("Rotating the bootstrap client secret will invalidate those envs until they re-run: hyops init azure")
                if not allow_shared_sp:
                    if not (os.isatty(0) and os.isatty(1)):
                        print("ERR: refusing to bootstrap/rotate a shared SP secret without a TTY prompt.")
                        print("hint: set a unique AZ_SP_NAME per env (recommended), or re-run with: --allow-shared-sp")
                        print(f"run record: {evidence_dir}")
                        return OPERATOR_ERROR
                    try:
                        answer = input("continue with shared AZ_SP_NAME? [y/N]: ")
                    except EOFError:
                        answer = ""
                    if str(answer or "").strip().lower() not in ("y", "yes"):
                        print("cancelled. set a unique AZ_SP_NAME and re-run.")
                        print(f"config: {config_path}")
                        return OPERATOR_ERROR

            if subscription_id:
                if not _az_ok(["account", "set", "--subscription", subscription_id], evidence_dir, "az_account_set_initial"):
                    print(f"ERR: failed to select subscription: {subscription_id}")
                    return TARGET_EXEC_FAILURE

            if not tenant_id:
                tenant_id = _az_tsv(["account", "show", "--query", "tenantId", "-o", "tsv"], evidence_dir, "az_account_tenant_interactive")
            if not subscription_id:
                subscription_id = _az_tsv(["account", "show", "--query", "id", "-o", "tsv"], evidence_dir, "az_account_subscription_interactive")

            if not subscription_id or not tenant_id:
                print("ERR: missing subscription/tenant from active Azure context")
                return TARGET_EXEC_FAILURE

            app_id = _az_tsv(
                ["ad", "sp", "list", "--display-name", sp_name, "--query", "[0].appId", "-o", "tsv"],
                evidence_dir,
                "az_sp_list",
            )

            if app_id:
                client_id = app_id
                r = run_capture_sensitive(
                    [
                        "az",
                        "ad",
                        "sp",
                        "credential",
                        "reset",
                        "--id",
                        client_id,
                        "--query",
                        "password",
                        "-o",
                        "tsv",
                        "--only-show-errors",
                    ],
                    evidence_dir=evidence_dir,
                    label="az_sp_credential_reset",
                )
                secret = _last_nonempty_line(r.stdout)
                if r.rc != 0 or not secret:
                    detail = _first_nonempty_line(r.stderr)
                    if detail:
                        print(f"ERR: service principal credential reset failed: {detail}")
                    else:
                        print("ERR: service principal credential reset failed")
                    print(f"run record: {evidence_dir}")
                    print(
                        "hint: login with `az login` as a user with permission to manage service principals, or use --non-interactive with pre-seeded secrets."
                    )
                    return TARGET_EXEC_FAILURE
                client_secret = secret
                rotated_or_created = True
            else:
                r = run_capture_sensitive(
                    [
                        "az",
                        "ad",
                        "sp",
                        "create-for-rbac",
                        "--name",
                        sp_name,
                        "--skip-assignment",
                        "--query",
                        "[appId,password]",
                        "-o",
                        "tsv",
                        "--only-show-errors",
                    ],
                    evidence_dir=evidence_dir,
                    label="az_sp_create_for_rbac",
                )
                if r.rc != 0:
                    detail = _first_nonempty_line(r.stderr)
                    if detail:
                        print(f"ERR: failed to create bootstrap service principal: {detail}")
                    else:
                        print("ERR: failed to create bootstrap service principal")
                    print(f"run record: {evidence_dir}")
                    print(
                        "hint: login with `az login` as a user with permission to create service principals, or use --non-interactive with pre-seeded secrets."
                    )
                    return TARGET_EXEC_FAILURE

                cid, csecret = _parse_tsv_pair(_last_nonempty_line(r.stdout))
                if not cid or not csecret:
                    print("ERR: bootstrap service principal output was incomplete")
                    return TARGET_EXEC_FAILURE
                client_id = cid
                client_secret = csecret
                rotated_or_created = True

            # Persist immediately so a failure below doesn't lose the rotated secret.
            try:
                merge_set(
                    vault_path,
                    auth,
                    {
                        "AZ_CLIENT_ID": client_id,
                        "AZ_CLIENT_SECRET": client_secret,
                        "AZ_TENANT_ID": tenant_id,
                        "AZ_SUBSCRIPTION_ID": subscription_id,
                    },
                )
                vault_persisted = True
            except Exception as e:
                print(f"ERR: vault persistence failed: {e}")
                print(f"run record: {evidence_dir}")
                return VAULT_FAILURE

            # Ensure subscription roles while we're still authenticated as a user (before SP login changes az context).
            if not _ensure_subscription_roles(evidence_dir, subscription_id, client_id):
                print("ERR: failed to ensure Azure role assignments for bootstrap service principal")
                print(f"run record: {evidence_dir}")
                return TARGET_EXEC_FAILURE
            roles_ensured = True

            # Best-effort: directory role assignment (may require elevated tenant permissions).
            _ensure_directory_role_best_effort(evidence_dir, client_id)

            ok, detail = _az_login_sp_retry(
                evidence_dir=evidence_dir,
                label="az_login_sp_new",
                client_id=client_id,
                client_secret=client_secret,
                tenant_id=tenant_id,
                allow_no_subscriptions=True,
            )
            if not ok and detail and "AADSTS7000215" in detail:
                # Fallback: in some environments `az ad sp credential reset` output can be misleading.
                # Try rotating via the app credential reset endpoint and attempt login again.
                r2 = run_capture_sensitive(
                    [
                        "az",
                        "ad",
                        "app",
                        "credential",
                        "reset",
                        "--id",
                        client_id,
                        "--query",
                        "password",
                        "-o",
                        "tsv",
                        "--only-show-errors",
                    ],
                    evidence_dir=evidence_dir,
                    label="az_app_credential_reset_fallback",
                )
                secret2 = _last_nonempty_line(r2.stdout)
                if r2.rc == 0 and secret2:
                    client_secret = secret2
                    try:
                        merge_set(
                            vault_path,
                            auth,
                            {
                                "AZ_CLIENT_ID": client_id,
                                "AZ_CLIENT_SECRET": client_secret,
                                "AZ_TENANT_ID": tenant_id,
                                "AZ_SUBSCRIPTION_ID": subscription_id,
                            },
                        )
                        vault_persisted = True
                    except Exception:
                        # Best-effort; still attempt login with the candidate secret.
                        pass

                    ok, detail = _az_login_sp_retry(
                        evidence_dir=evidence_dir,
                        label="az_login_sp_new_fallback",
                        client_id=client_id,
                        client_secret=client_secret,
                        tenant_id=tenant_id,
                        allow_no_subscriptions=True,
                    )
            if not ok:
                if detail:
                    print(f"ERR: failed to authenticate with bootstrap service principal: {detail}")
                else:
                    print("ERR: failed to authenticate with bootstrap service principal")
                if detail and "AADSTS7000215" in detail and _looks_like_guid(client_secret):
                    print("note: Azure returned an invalid client secret error and the captured secret looks like a GUID.")
                    print("this usually indicates a secret ID (keyId) was used instead of the secret value.")
                print(f"run record: {evidence_dir}")
                return TARGET_EXEC_FAILURE

            # Role assignments can take time to propagate. Retry subscription selection for the SP.
            if subscription_id:
                for attempt in range(1, 7):
                    if _az_ok(["account", "set", "--subscription", subscription_id], evidence_dir, f"az_account_set_sp_try{attempt}"):
                        break
                    time.sleep(min(5 * attempt, 20))
                else:
                    print("ERR: bootstrap service principal cannot access the subscription yet (role propagation delay?)")
                    print("hint: wait 1-2 minutes and re-run: hyops init azure --env <env> --with-cli-login")
                    print(f"run record: {evidence_dir}")
                    return TARGET_EXEC_FAILURE

    if subscription_id:
        if not _az_ok(["account", "set", "--subscription", subscription_id], evidence_dir, "az_account_set_final"):
            print(f"ERR: cannot access configured Azure subscription: {subscription_id}")
            print(
                "hint: the subscription may belong to another tenant, or the current Azure identity "
                "may no longer have access to it."
            )
            print(
                "hint: re-run `hyops init azure --env <env> --with-cli-login --force` to review or replace "
                "the configured subscription and tenant."
            )
            print(f"run record: {evidence_dir}")
            return TARGET_EXEC_FAILURE

    if not subscription_id:
        subscription_id = _az_tsv(["account", "show", "--query", "id", "-o", "tsv"], evidence_dir, "az_account_subscription_final")
    if not tenant_id:
        tenant_id = _az_tsv(["account", "show", "--query", "tenantId", "-o", "tsv"], evidence_dir, "az_account_tenant_final")

    if not subscription_id or not tenant_id:
        print("ERR: missing subscription/tenant after Azure authentication")
        return TARGET_EXEC_FAILURE

    # Role assignment mutations are only safe/reliable during interactive bootstrap (user identity).
    if rotated_or_created and not roles_ensured:
        if not _ensure_subscription_roles(evidence_dir, subscription_id, client_id):
            print("ERR: failed to ensure Azure role assignments for bootstrap service principal")
            print(f"run record: {evidence_dir}")
            return TARGET_EXEC_FAILURE

    # Directory role assignment is best-effort; it is attempted during interactive bootstrap.

    if not getattr(ns, "non_interactive", False):
        should_persist = bool(has_vault_password and (rotated_or_created or vault_env))
        if rotated_or_created and not has_vault_password:
            print("ERR: vault password source required to persist rotated credentials")
            return VAULT_FAILURE

        if should_persist and not vault_persisted:
            try:
                merge_set(
                    vault_path,
                    auth,
                    {
                        "AZ_CLIENT_ID": client_id,
                        "AZ_CLIENT_SECRET": client_secret,
                        "AZ_TENANT_ID": tenant_id,
                        "AZ_SUBSCRIPTION_ID": subscription_id,
                    },
                )
            except Exception as e:
                print(f"ERR: vault persistence failed: {e}")
                return VAULT_FAILURE

    if tfvars_out.exists() and not getattr(ns, "force", False):
        print(f"ERR: credentials file already exists (use --force to overwrite): {tfvars_out}")
        return OPERATOR_ERROR

    try:
        tfvars_out.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            "# <sensitive> Do not commit.\n"
            "# purpose: Azure runtime credentials for Terraform stacks.\n"
            "# </sensitive>\n\n"
            f'subscription_id = "{subscription_id}"\n'
            f'tenant_id       = "{tenant_id}"\n'
            f'client_id       = "{client_id}"\n'
            f'client_secret   = "{client_secret}"\n'
            f'location        = "{location}"\n'
        )
        tfvars_out.write_text(payload, encoding="utf-8")
        os.chmod(tfvars_out, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        print("ERR: failed to write Azure credentials tfvars")
        return WRITE_FAILURE

    try:
        write_marker(
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
                    "evidence": str(evidence_dir),
                },
                "context": {
                    "subscription_id": subscription_id,
                    "tenant_id": tenant_id,
                    "location": location,
                },
            },
        )
    except Exception:
        print("ERR: failed to write readiness marker")
        return WRITE_FAILURE

    print(f"target={target} status=ready run_id={run_id}")
    print(f"run record: {evidence_dir}")
    print(f"readiness: {readiness_file}")
    print(f"credentials: {tfvars_out}")

    if bool(getattr(ns, "logout_after", False)):
        # Best-effort cleanup; do not fail init if logout fails.
        _az_ok(["logout"], evidence_dir, "az_logout")

    return OK


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _truthy(raw: str) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _envs_root_for_scan(paths) -> Path | None:
    """Find the envs root so we can detect shared config across envs.

    Supported layouts:
      - ~/.hybridops/envs/<env> (env root)
      - ~/.hybridops (workstation root)
    """

    try:
        if paths.root.parent.name == "envs":
            return paths.root.parent
    except Exception:
        pass

    candidate = paths.root / "envs"
    if candidate.is_dir():
        return candidate
    return None


def _other_envs_with_same_sp_name(paths, current_env: str, sp_name: str) -> list[str]:
    envs_root = _envs_root_for_scan(paths)
    if not envs_root:
        return []

    cur = str(current_env or "").strip()
    name = str(sp_name or "").strip()
    if not name:
        return []

    matches: list[str] = []
    try:
        children = sorted([p for p in envs_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    except Exception:
        return []

    for env_dir in children:
        env_name = env_dir.name
        if cur and env_name == cur:
            continue
        cfg_file = env_dir / "config" / "azure.conf"
        if not cfg_file.exists():
            continue
        try:
            other = (read_kv_file(cfg_file).get("AZ_SP_NAME") or "").strip()
        except Exception:
            continue
        if other == name:
            matches.append(env_name)
    return matches


def _review_detected_azure_defaults_interactive(
    *,
    env_name: str,
    location: str,
    location_source: str,
    sp_name: str,
    sp_name_source: str,
    subscription_id: str,
    subscription_id_source: str,
    tenant_id: str,
    tenant_id_source: str,
) -> tuple[str, str, str, str]:
    label = env_name or "<env>"
    print(f"review effective Azure defaults for env {label}:")
    print(f"  location: {location or '<unset>'} (source={location_source or 'unset'})")
    print(f"  sp_name: {sp_name or '<unset>'} (source={sp_name_source or 'unset'})")
    if subscription_id:
        print(f"  subscription_id: {subscription_id} (source={subscription_id_source})")
    if tenant_id:
        print(f"  tenant_id: {tenant_id} (source={tenant_id_source})")
    print("press Enter to keep a value, type a replacement, or type 'auto' to clear subscription/tenant and derive them from the active Azure context.")

    try:
        location_ans = str(input(f"Azure location [{location}]: ") or "").strip()
    except EOFError:
        location_ans = ""
    except KeyboardInterrupt:
        print()
        return location, sp_name, subscription_id, tenant_id
    if location_ans:
        location = location_ans

    try:
        sp_name_ans = str(input(f"Bootstrap SP name [{sp_name}]: ") or "").strip()
    except EOFError:
        sp_name_ans = ""
    except KeyboardInterrupt:
        print()
        return location, sp_name, subscription_id, tenant_id
    if sp_name_ans:
        sp_name = sp_name_ans

    try:
        sub_ans = str(input(f"Azure subscription id [{subscription_id}]: ") or "").strip()
    except EOFError:
        sub_ans = ""
    except KeyboardInterrupt:
        print()
        return location, sp_name, subscription_id, tenant_id
    if sub_ans.lower() == "auto":
        subscription_id = ""
    elif sub_ans:
        subscription_id = sub_ans

    try:
        tenant_ans = str(input(f"Azure tenant id [{tenant_id}]: ") or "").strip()
    except EOFError:
        tenant_ans = ""
    except KeyboardInterrupt:
        print()
        return location, sp_name, subscription_id, tenant_id
    if tenant_ans.lower() == "auto":
        tenant_id = ""
    elif tenant_ans:
        tenant_id = tenant_ans

    return location, sp_name, subscription_id, tenant_id


def _az_tsv(argv: list[str], evidence_dir: Path, label: str) -> str:
    r = run_capture(["az", *argv], evidence_dir=evidence_dir, label=label, redact=True)
    if r.rc != 0:
        return ""
    return (r.stdout or "").strip()


def _az_ok(argv: list[str], evidence_dir: Path, label: str) -> bool:
    r = run_capture(["az", *argv], evidence_dir=evidence_dir, label=label, redact=True)
    return r.rc == 0


def _az_login_sp(
    evidence_dir: Path,
    label: str,
    client_id: str,
    client_secret: str,
    tenant_id: str,
    *,
    allow_no_subscriptions: bool = False,
) -> tuple[bool, str]:
    if not client_id or not client_secret or not tenant_id:
        return False, "missing client_id/client_secret/tenant_id"

    env = os.environ.copy()
    env.update(
        {
            "AZ_CLIENT_ID": client_id,
            "AZ_CLIENT_SECRET": client_secret,
            "AZ_TENANT_ID": tenant_id,
        }
    )

    allow = " --allow-no-subscriptions" if allow_no_subscriptions else ""
    r = run_capture_sensitive(
        [
            "/bin/bash",
            "-lc",
            "az login --service-principal --username \"$AZ_CLIENT_ID\" --password \"$AZ_CLIENT_SECRET\" --tenant \"$AZ_TENANT_ID\" --only-show-errors --output none"
            + allow,
        ],
        evidence_dir=evidence_dir,
        label=label,
        env=env,
        timeout_s=30,
    )
    if r.rc != 0:
        return False, _first_nonempty_line(r.stderr)
    return True, ""


def _az_login_sp_retry(
    *,
    evidence_dir: Path,
    label: str,
    client_id: str,
    client_secret: str,
    tenant_id: str,
    allow_no_subscriptions: bool,
    attempts: int = 6,
) -> tuple[bool, str]:
    ok, detail = _az_login_sp(
        evidence_dir=evidence_dir,
        label=label,
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=tenant_id,
        allow_no_subscriptions=allow_no_subscriptions,
    )
    if ok:
        return True, ""

    # Retry: tenant/app replication can lag immediately after credential rotation.
    for attempt in range(1, max(1, attempts) + 1):
        time.sleep(min(5 * attempt, 20))
        ok, detail = _az_login_sp(
            evidence_dir=evidence_dir,
            label=f"{label}_try{attempt}",
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
            allow_no_subscriptions=allow_no_subscriptions,
        )
        if ok:
            return True, ""
    return False, detail


def _ensure_subscription_roles(evidence_dir: Path, subscription_id: str, assignee: str) -> bool:
    if not subscription_id or not assignee:
        return False

    scope = f"/subscriptions/{subscription_id}"

    contributor_count = _az_tsv(
        [
            "role",
            "assignment",
            "list",
            "--assignee",
            assignee,
            "--role",
            "Contributor",
            "--scope",
            scope,
            "--query",
            "length(@)",
            "-o",
            "tsv",
        ],
        evidence_dir,
        "az_role_contributor_list",
    )
    if contributor_count in ("", "0"):
        if not _az_ok(
            [
                "role",
                "assignment",
                "create",
                "--assignee",
                assignee,
                "--role",
                "Contributor",
                "--scope",
                scope,
            ],
            evidence_dir,
            "az_role_contributor_create",
        ):
            return False

    uaa_count = _az_tsv(
        [
            "role",
            "assignment",
            "list",
            "--assignee",
            assignee,
            "--role",
            "User Access Administrator",
            "--scope",
            scope,
            "--query",
            "length(@)",
            "-o",
            "tsv",
        ],
        evidence_dir,
        "az_role_uaa_list",
    )
    if uaa_count in ("", "0"):
        _az_ok(
            [
                "role",
                "assignment",
                "create",
                "--assignee",
                assignee,
                "--role",
                "User Access Administrator",
                "--scope",
                scope,
            ],
            evidence_dir,
            "az_role_uaa_create",
        )

    return True


def _ensure_directory_role_best_effort(evidence_dir: Path, client_id: str) -> None:
    if not client_id:
        return

    sp_object_id = _az_tsv(
        ["ad", "sp", "show", "--id", client_id, "--query", "id", "-o", "tsv"],
        evidence_dir,
        "az_sp_object_id",
    )
    if not sp_object_id:
        return

    app_admin_def_id = "9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3"
    filter_expr = (
        f"principalId eq '{sp_object_id}' and roleDefinitionId eq '{app_admin_def_id}' and directoryScopeId eq '/'"
    )

    count = _az_tsv(
        [
            "rest",
            "--method",
            "GET",
            "--uri",
            f"https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments?$filter={filter_expr}",
            "--query",
            "value | length(@)",
            "-o",
            "tsv",
        ],
        evidence_dir,
        "az_dir_role_list",
    )
    if count not in ("", "0"):
        return

    _az_ok(
        [
            "rest",
            "--method",
            "POST",
            "--uri",
            "https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments",
            "--headers",
            "Content-Type=application/json",
            "--body",
            (
                '{"principalId":"'
                + sp_object_id
                + '","roleDefinitionId":"'
                + app_admin_def_id
                + '","directoryScopeId":"/"}'
            ),
        ],
        evidence_dir,
        "az_dir_role_create",
    )


def _first_nonempty_line(text: str) -> str:
    for raw in (text or "").splitlines():
        line = str(raw or "").strip()
        if line:
            return line
    return ""


def _last_nonempty_line(text: str) -> str:
    last = ""
    for raw in (text or "").splitlines():
        line = str(raw or "").strip()
        if line:
            last = line
    return last


def _looks_like_guid(text: str) -> bool:
    try:
        uuid.UUID(str(text or "").strip())
        return True
    except Exception:
        return False


def _parse_tsv_pair(text: str) -> tuple[str, str]:
    parts = [p.strip() for p in text.split() if p.strip()]
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[1]
