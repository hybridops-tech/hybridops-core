"""
purpose: Initialise GCP target runtime inputs using ADC + service account impersonation.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import tempfile
from pathlib import Path

from hyops.runtime.exitcodes import (
    CONFIG_TEMPLATE_WRITTEN,
    OK,
    OPERATOR_ERROR,
    TARGET_EXEC_FAILURE,
    WRITE_FAILURE,
)
from hyops.init.helpers import init_evidence_path, init_run_id, read_kv_file
from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.layout import ensure_layout
from hyops.runtime.gcp import (
    diagnose_billing_association_permission,
    diagnose_private_service_access_permissions,
    normalize_billing_account_id,
)
from hyops.runtime.paths import RuntimePaths
from hyops.runtime.proc import run_capture, run_capture_interactive
from hyops.runtime.readiness import write_marker
from hyops.runtime.root import resolve_runtime_root
from hyops.runtime.state import write_json
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.module_state import read_module_state
from hyops.runtime.vault import VaultAuth, merge_set, read_env


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser(
        "gcp",
        help="Initialise GCP runtime inputs and prerequisites.",
        epilog=(
            "Notes:\n"
            "  - Shared flags live on `hyops init` (e.g. --root, --out-dir, --config, --dry-run).\n"
            "  - Required steady-state config keys: GCP_PROJECT_ID, GCP_REGION.\n"
            "  - With --with-cli-login, HybridOps can derive them from gcloud defaults or prompt interactively.\n"
            "  - Optional: GCP_BILLING_ACCOUNT_ID (used by org/gcp/project-factory when creating new projects).\n"
            "  - Optional: GCP_TERRAFORM_SA_EMAIL (recommended for steady-state; can be derived from project-factory state).\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    add_init_shared_args(p)

    p.add_argument("--project-id", default=None, help="Override GCP project id.")
    p.add_argument("--region", default=None, help="Override GCP region.")
    p.add_argument(
        "--billing-account-id",
        default=None,
        help="Override GCP billing account id (used by org/gcp/project-factory).",
    )
    p.add_argument(
        "--terraform-sa-email",
        default=None,
        help="Override Terraform runtime service account email (impersonation target).",
    )
    p.add_argument(
        "--adc-quota-project-id",
        default=None,
        help="Override ADC quota project id (application-default set-quota-project).",
    )
    p.add_argument("--tfvars-out", default=None, help="Override credentials tfvars output path.")
    p.add_argument("--ssh-public-key", default=None, help="Override or persist a non-secret SSH public key into GCP init readiness.")
    p.add_argument(
        "--with-eso-sa",
        action="store_true",
        default=False,
        help=(
            "Generate a key for the ESO GCP service account and persist it as "
            "HYOPS_GSM_SA_KEY_JSON in the bootstrap vault. "
            "Requires org/gcp/gsm-eso-sa to have been applied first (creates the SA, "
            "grants roles/secretmanager.secretAccessor, and lifts the key creation constraint). "
            "Skipped if the key is already present (use --force to reprovision)."
        ),
    )
    p.add_argument(
        "--eso-sa-name",
        default="eso-gsm-reader",
        help="Service account name to create or reuse for ESO (default: eso-gsm-reader).",
    )
    p.set_defaults(_handler=run)


def run(ns) -> int:
    root = resolve_runtime_root(getattr(ns, "root", None), getattr(ns, "env", None))
    paths = RuntimePaths.from_root(root)
    ensure_layout(paths)

    target = "gcp"
    run_id = init_run_id("init-gcp")

    evidence_dir = init_evidence_path(
        root=paths.root,
        out_dir=getattr(ns, "out_dir", None),
        target=target,
        run_id=run_id,
    )

    config_path = (
        Path(ns.config).expanduser().resolve()
        if getattr(ns, "config", None)
        else (paths.config_dir / "gcp.conf")
    )

    try:
        stamp_runtime(
            paths.root,
            command="init",
            target=target,
            run_id=run_id,
            evidence_dir=evidence_dir,
            extra={
                "config": str(config_path),
                "readiness": str(paths.meta_dir / f"{target}.ready.json"),
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

    if not config_path.exists():
        _write_config_template(config_path)
        write_json(
            evidence_dir / "meta.json",
            {
                "target": target,
                "run_id": run_id,
                "status": "needs_config",
                "paths": {
                    "root": str(paths.root),
                    "config": str(config_path),
                    "readiness": str(paths.meta_dir / f"{target}.ready.json"),
                    "evidence_dir": str(evidence_dir),
                },
            },
        )
        print(f"wrote config template: {config_path}")
        if not bool(getattr(ns, "with_cli_login", False)):
            print("edit the file and re-run: hyops init gcp")
            return CONFIG_TEMPLATE_WRITTEN
        print("config template created; continuing with interactive discovery.")
    elif bool(getattr(ns, "force", False)):
        if _ensure_gcp_config_keys(config_path):
            print(f"updated config template: {config_path}")

    cfg = read_kv_file(config_path)

    project_id = ""
    project_id_source = ""
    if getattr(ns, "project_id", None):
        project_id = str(getattr(ns, "project_id", None) or "").strip()
        project_id_source = "flag"
    elif os.environ.get("GCP_PROJECT_ID"):
        project_id = str(os.environ.get("GCP_PROJECT_ID") or "").strip()
        project_id_source = "env"
    elif cfg.get("GCP_PROJECT_ID"):
        project_id = str(cfg.get("GCP_PROJECT_ID") or "").strip()
        project_id_source = "config"

    region = ""
    region_source = ""
    if getattr(ns, "region", None):
        region = str(getattr(ns, "region", None) or "").strip()
        region_source = "flag"
    elif os.environ.get("GCP_REGION"):
        region = str(os.environ.get("GCP_REGION") or "").strip()
        region_source = "env"
    elif cfg.get("GCP_REGION"):
        region = str(cfg.get("GCP_REGION") or "").strip()
        region_source = "config"

    billing_account_id = ""
    billing_account_source = ""
    if getattr(ns, "billing_account_id", None):
        billing_account_id = normalize_billing_account_id(str(getattr(ns, "billing_account_id", None) or "").strip())
        billing_account_source = "flag"
    elif os.environ.get("GCP_BILLING_ACCOUNT_ID"):
        billing_account_id = normalize_billing_account_id(str(os.environ.get("GCP_BILLING_ACCOUNT_ID") or "").strip())
        billing_account_source = "env"
    elif cfg.get("GCP_BILLING_ACCOUNT_ID"):
        billing_account_id = normalize_billing_account_id(str(cfg.get("GCP_BILLING_ACCOUNT_ID") or "").strip())
        billing_account_source = "config"
    terraform_sa_email = (
        getattr(ns, "terraform_sa_email", None)
        or os.environ.get("GCP_TERRAFORM_SA_EMAIL")
        or cfg.get("GCP_TERRAFORM_SA_EMAIL")
        or ""
    ).strip()
    terraform_sa_email_explicit = bool(terraform_sa_email)
    adc_quota_project_id = (
        (
            getattr(ns, "adc_quota_project_id", None)
            or os.environ.get("GCP_ADC_QUOTA_PROJECT_ID")
            or cfg.get("GCP_ADC_QUOTA_PROJECT_ID")
            or ""
        ).strip()
    )
    ssh_public_key = (
        getattr(ns, "ssh_public_key", None)
        or os.environ.get("GCP_SSH_PUBLIC_KEY")
        or cfg.get("GCP_SSH_PUBLIC_KEY")
        or _read_first_pubkey()
        or ""
    ).strip()

    tfvars_out_raw = (
        getattr(ns, "tfvars_out", None)
        or (os.environ.get("GCP_TFVARS_OUT") or "").strip()
        or (cfg.get("GCP_TFVARS_OUT") or "").strip()
        or str(paths.credentials_dir / "gcp.credentials.tfvars")
    )
    tfvars_out = Path(tfvars_out_raw).expanduser().resolve()

    if not terraform_sa_email:
        terraform_sa_email = _terraform_sa_from_state(paths.state_dir)

    if project_id or region:
        _upsert_kv_file(
            config_path,
            {
                "GCP_PROJECT_ID": project_id,
                "GCP_REGION": region,
                "GCP_BILLING_ACCOUNT_ID": billing_account_id,
            },
        )

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
                "root": str(paths.root),
                "config": str(config_path),
                "tfvars_out": str(tfvars_out),
                "readiness": str(paths.meta_dir / f"{target}.ready.json"),
                "evidence_dir": str(evidence_dir),
            },
            "inputs": {
                "project_id": project_id,
                "region": region,
                "billing_account_id": billing_account_id,
                "terraform_sa_email": terraform_sa_email,
                "adc_quota_project_id": adc_quota_project_id,
                "ssh_public_key_present": bool(ssh_public_key),
            },
        },
    )

    if getattr(ns, "dry_run", False):
        print("dry-run: would validate gcloud + adc (and impersonation when configured), then write tfvars + readiness")
        print(f"run record: {evidence_dir}")
        return OK

    if os.environ.get("CI") and not getattr(ns, "non_interactive", False):
        print("ERR: interactive gcp init must not run in CI (use --non-interactive)")
        return OPERATOR_ERROR

    if not _cmd_ok(["gcloud", "--version"], evidence_dir, "gcloud_version"):
        print("ERR: gcloud not available; install with: hyops setup cloud-gcp --sudo")
        print(f"run record: {evidence_dir}")
        return OPERATOR_ERROR

    non_interactive = bool(getattr(ns, "non_interactive", False))

    active_account = _first_nonempty_line(
        _cmd_stdout(
            ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
            evidence_dir,
            "gcloud_auth_list",
        )
    )
    if not active_account:
        if non_interactive:
            # CI runners typically provide a service-account JSON key. If present, try to activate it.
            key_file = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
            if key_file and Path(key_file).expanduser().exists():
                r = run_capture(
                    ["gcloud", "auth", "activate-service-account", "--key-file", key_file, "--quiet"],
                    evidence_dir=evidence_dir,
                    label="gcloud_auth_activate_service_account",
                    redact=True,
                )
                if r.rc != 0:
                    print("ERR: failed to activate service account from GOOGLE_APPLICATION_CREDENTIALS; see run record")
                    print(f"run record: {evidence_dir}")
                    return TARGET_EXEC_FAILURE

                active_account = _first_nonempty_line(
                    _cmd_stdout(
                        ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                        evidence_dir,
                        "gcloud_auth_list_after_activation",
                    )
                )

            if not active_account:
                print("ERR: gcloud auth is required (no active account).")
                print("hint: set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON key, or activate explicitly:")
                print("  gcloud auth activate-service-account --key-file <path> --quiet")
                print(f"run record: {evidence_dir}")
                return OPERATOR_ERROR
        else:
            if not bool(getattr(ns, "with_cli_login", False)):
                print("ERR: gcloud auth is required (no active account).")
                print("Option A: run `gcloud auth login` (workstations) then re-run: hyops init gcp")
                print("Option B: run `gcloud auth activate-service-account --key-file <path>` (CI/runners)")
                print("Option C: re-run with: hyops init gcp --with-cli-login")
                print(f"run record: {evidence_dir}")
                return OPERATOR_ERROR

            if not _require_tty():
                print("ERR: interactive authentication requires a TTY")
                print(f"run record: {evidence_dir}")
                return OPERATOR_ERROR

            print("starting interactive gcloud login; follow the prompts shown below.")
            r = run_capture_interactive(
                ["gcloud", "auth", "login", "--no-launch-browser"],
                evidence_dir=evidence_dir,
                label="gcloud_auth_login",
                redact=True,
            )
            if r.rc != 0:
                print("ERR: gcloud auth login failed; see run record")
                print(f"run record: {evidence_dir}")
                return TARGET_EXEC_FAILURE

            active_account = _first_nonempty_line(
                _cmd_stdout(
                    ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                    evidence_dir,
                    "gcloud_auth_list_after_login",
                )
            )
            if not active_account:
                print("ERR: gcloud auth login did not yield an active account")
                print(f"run record: {evidence_dir}")
                return TARGET_EXEC_FAILURE

    # Make the active identity explicit when interactive flows are allowed.
    if (not non_interactive) and bool(getattr(ns, "with_cli_login", False)) and active_account:
        env_name = str(getattr(ns, "env", "") or "").strip()
        print(f"gcp identity: account={active_account}")
        if env_name:
            print(f"target env: {env_name}")
        if _require_tty():
            try:
                answer = input("continue with this gcloud identity? [y/N]: ")
            except EOFError:
                answer = ""
            if str(answer or "").strip().lower() not in ("y", "yes"):
                print("cancelled. switch identity and re-run.")
                print("suggested:")
                print("  gcloud auth revoke --all")
                print("  gcloud auth login")
                return OPERATOR_ERROR

    if not _shell_ok(
        "gcloud auth application-default print-access-token >/dev/null",
        evidence_dir,
        "adc_token_check",
    ):
        if getattr(ns, "non_interactive", False):
            print("ERR: ADC not available; run gcloud auth application-default login or provide ADC in CI")
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR
        if not bool(getattr(ns, "with_cli_login", False)):
            print("ERR: ADC not available.")
            print("Run: gcloud auth application-default login")
            print("Then re-run: hyops init gcp")
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR
        if not _run_interactive_adc_login(evidence_dir, reason="ADC is required for GCP bootstrap and Terraform authentication."):
            return TARGET_EXEC_FAILURE

    # Ensure the operator account holds roles/orgpolicy.policyAdmin on the org.
    # This is required by _ensure_terraform_sa_project_roles (below) which sets
    # the project-level iam.disableServiceAccountKeyCreation override using ADC.
    # Best-effort: non-fatal if no org is found or the role is already present.
    if not non_interactive and bool(getattr(ns, "with_cli_login", False)) and active_account:
        _ensure_org_policy_admin(
            account=active_account,
            evidence_dir=evidence_dir,
        )

    if not project_id:
        project_id = _normalize_gcloud_value(
            _cmd_stdout(
                ["gcloud", "config", "get-value", "project"],
                evidence_dir,
                "gcloud_config_project",
            )
        )
        if project_id:
            project_id_source = "gcloud"
    if not region:
        region = _normalize_gcloud_value(
            _cmd_stdout(
                ["gcloud", "config", "get-value", "compute/region"],
                evidence_dir,
                "gcloud_config_region",
            )
        )
        if region:
            region_source = "gcloud"
    if not region:
        zone = _normalize_gcloud_value(
            _cmd_stdout(
                ["gcloud", "config", "get-value", "compute/zone"],
                evidence_dir,
                "gcloud_config_zone",
            )
        )
        if zone:
            region = _region_from_zone(zone)
            if region:
                region_source = "gcloud"

    if (not project_id or not region) and not non_interactive and bool(getattr(ns, "with_cli_login", False)):
        if not _require_tty():
            print("ERR: interactive project/region discovery requires a TTY")
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR
        if not project_id:
            try:
                project_id = str(input("GCP project id: ") or "").strip()
                if project_id:
                    project_id_source = "prompt"
            except EOFError:
                project_id = ""
            except KeyboardInterrupt:
                print()
                return OPERATOR_ERROR
        if not region:
            try:
                region = str(input("GCP region: ") or "").strip()
                if region:
                    region_source = "prompt"
            except EOFError:
                region = ""
            except KeyboardInterrupt:
                print()
                return OPERATOR_ERROR

    if (not billing_account_id) and not non_interactive and bool(getattr(ns, "with_cli_login", False)):
        if not _require_tty():
            print("ERR: interactive billing-account discovery requires a TTY")
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR
        billing_accounts = _discover_open_billing_accounts(evidence_dir)
        billing_account_id, billing_account_source = _select_billing_account_interactive(billing_accounts)

    if (
        not non_interactive
        and bool(getattr(ns, "with_cli_login", False))
        and _require_tty()
        and (
            any(src == "gcloud" for src in (project_id_source, region_source, billing_account_source))
            or (
                bool(getattr(ns, "force", False))
                and any(src in {"config", "env"} for src in (project_id_source, region_source, billing_account_source))
            )
        )
    ):
        project_id, region, billing_account_id = _review_detected_gcp_defaults_interactive(
            env_name=str(getattr(ns, "env", "") or "").strip(),
            project_id=project_id,
            project_id_source=project_id_source,
            region=region,
            region_source=region_source,
            billing_account_id=billing_account_id,
            billing_account_source=billing_account_source,
        )

    if project_id or region or billing_account_id:
        _upsert_kv_file(
            config_path,
            {
                "GCP_PROJECT_ID": project_id,
                "GCP_REGION": region,
                "GCP_BILLING_ACCOUNT_ID": billing_account_id,
            },
        )

    if not project_id or not region:
        print(
            f"ERR: required config missing in {config_path} "
            f"(GCP_PROJECT_ID, GCP_REGION)"
        )
        print("hint: set them in gcp.conf, run `gcloud config set project ...` and `gcloud config set compute/region ...`,")
        print("hint: or re-run with --with-cli-login and answer the prompts.")
        print(f"run record: {evidence_dir}")
        return OPERATOR_ERROR

    project_access = _diagnose_gcp_project_access(project_id, evidence_dir)
    project_access_validated = bool(project_access[0])
    project_bootstrap_pending = False
    if not project_access_validated:
        replacement_project_id = ""
        if not non_interactive and bool(getattr(ns, "with_cli_login", False)) and _require_tty():
            print(
                "WARN: configured GCP project is not accessible to the active account "
                f"({active_account or 'unknown'}): {project_id}"
            )
            print(_format_project_access_hint(project_id, project_access[1]))
            try:
                replacement_project_id = str(
                    input("Replacement GCP project id (leave blank to abort): ") or ""
                ).strip()
            except EOFError:
                replacement_project_id = ""
            except KeyboardInterrupt:
                print()
                return OPERATOR_ERROR
        if replacement_project_id:
            project_id = replacement_project_id
            project_id_source = "prompt"
            _upsert_kv_file(config_path, {"GCP_PROJECT_ID": project_id})
            project_access = _diagnose_gcp_project_access(project_id, evidence_dir)
            project_access_validated = bool(project_access[0])

        bootstrap_project_allowed = (
            str(project_id_source or "").strip().lower() in {"flag", "prompt"}
            and bool(billing_account_id)
            and not terraform_sa_email_explicit
        )
        if not project_access_validated and bootstrap_project_allowed:
            project_bootstrap_pending = True
            print(
                f"WARN: target GCP project {project_id} is not accessible yet; entering bootstrap mode "
                "so org/gcp/project-factory can create or adopt it."
            )
            if project_access[1]:
                print(f"detail: {project_access[1]}")
            print(
                "hint: in bootstrap mode, only org/gcp/project-factory should run. "
                "After project creation, rerun: hyops init gcp --env <env> --force "
                f"--project-id {project_id} --region {region}"
            )
        if not project_access_validated and not project_bootstrap_pending:
            print(f"ERR: cannot access configured GCP project: {project_id}")
            print(_format_project_access_hint(project_id, project_access[1]))
            print(
                "hint: if this env should move to a new project, re-run:\n"
                "  hyops init gcp --env <env> --with-cli-login --force --project-id <new-project-id> --region <region>"
            )
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR

    if project_bootstrap_pending and billing_account_id:
        billing_ok, billing_detail, refresh_recommended = diagnose_billing_association_permission(billing_account_id)
        if (not billing_ok) and refresh_recommended and (not non_interactive) and bool(getattr(ns, "with_cli_login", False)):
            if _run_interactive_adc_login(
                evidence_dir,
                reason=(
                    "ADC is present but does not currently have the billing-account permission "
                    "needed for project bootstrap."
                ),
            ):
                billing_ok, billing_detail, refresh_recommended = diagnose_billing_association_permission(billing_account_id)
        if not billing_ok:
            print(
                "ERR: current ADC cannot associate new projects with the configured billing account "
                f"billingAccounts/{normalize_billing_account_id(billing_account_id)}"
            )
            if billing_detail:
                print(f"detail: {billing_detail}")
            print(
                "hint: ensure the active ADC principal has billing.resourceAssociations.create "
                "on the selected billing account, then re-run init."
            )
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR

    if adc_quota_project_id:
        run_capture(
            ["gcloud", "auth", "application-default", "set-quota-project", adc_quota_project_id],
            evidence_dir=evidence_dir,
            label="adc_set_quota_project",
            redact=True,
        )

    impersonation_validated = False
    auth_mode = "direct-adc"
    if not terraform_sa_email:
        if non_interactive:
            print("ERR: GCP_TERRAFORM_SA_EMAIL is required in --non-interactive mode")
            print("hint: set it in <root>/config/gcp.conf or export GCP_TERRAFORM_SA_EMAIL, then re-run.")
            print("hint: if you're bootstrapping a new project, run org/gcp/project-factory first, then re-run init.")
            print(f"run record: {evidence_dir}")
            return OPERATOR_ERROR
        # Bootstrap-friendly mode: allow running without an impersonation target.
        print("note: GCP_TERRAFORM_SA_EMAIL not set; skipping impersonation validation.")
        print("hint: after running org/gcp/project-factory, re-run: hyops init gcp --env <env> --force")
    else:
        imp_ok = _shell_ok(
            "gcloud auth print-access-token "
            f"--impersonate-service-account={shlex.quote(terraform_sa_email)} "
            f"--project={shlex.quote(project_id)} "
            ">/dev/null",
            evidence_dir,
            "impersonation_check",
        )
        if (
            (not imp_ok)
            and (not terraform_sa_email_explicit)
            and (not non_interactive)
            and bool(getattr(ns, "with_cli_login", False))
            and bool(active_account)
        ):
            if _bootstrap_impersonation_grant(
                active_account=active_account,
                project_id=project_id,
                terraform_sa_email=terraform_sa_email,
                evidence_dir=evidence_dir,
            ):
                imp_ok = _shell_ok(
                    "gcloud auth print-access-token "
                    f"--impersonate-service-account={shlex.quote(terraform_sa_email)} "
                    f"--project={shlex.quote(project_id)} "
                    ">/dev/null",
                    evidence_dir,
                    "impersonation_check_after_bootstrap_grant",
                )
        if not imp_ok:
            if not terraform_sa_email_explicit:
                print("WARN: derived Terraform service account failed impersonation validation; continuing without impersonation.")
                print(
                    "hint: set GCP_TERRAFORM_SA_EMAIL explicitly once caller permissions are correct, "
                    "or keep using direct ADC for this environment."
                )
                terraform_sa_email = ""
            else:
                print("ERR: impersonation validation failed; see run record")
                print("hint: caller must have roles/iam.serviceAccountTokenCreator on the target service account.")
                print("hint: ensure iamcredentials.googleapis.com is enabled in the target project.")
                print(f"run record: {evidence_dir}")
                return TARGET_EXEC_FAILURE
        impersonation_validated = bool(terraform_sa_email)
        if impersonation_validated:
            auth_mode = "impersonation"

    # Ensure the Terraform SA has the project-level roles it needs to run all
    # hyops modules. Runs as ADC using the operator's own credentials (which
    # have projectIamAdmin / editor via the org admin chain). Idempotent.
    if (
        impersonation_validated
        and project_access_validated
        and terraform_sa_email
        and bool(getattr(ns, "with_cli_login", False))
    ):
        _ensure_terraform_sa_project_roles(
            project_id=project_id,
            terraform_sa_email=terraform_sa_email,
            evidence_dir=evidence_dir,
        )
        private_service_access_ok, private_service_access_detail = diagnose_private_service_access_permissions(
            project_id=project_id,
            network_project_id=project_id,
            impersonate_service_account=terraform_sa_email,
        )
        if private_service_access_ok:
            print(
                f"terraform-sa-setup: validated private service networking permissions on {project_id}"
            )
        elif private_service_access_detail:
            print(
                "WARN: terraform-sa-setup could not validate private service networking permissions; "
                + private_service_access_detail
            )

    eso_sa_email = ""
    if bool(getattr(ns, "with_eso_sa", False)):
        if not project_access_validated:
            print("WARN: --with-eso-sa skipped: project access is not yet validated (bootstrap mode).")
            print("hint: run org/gcp/project-factory first, then re-run: hyops init gcp --env <env> --force --with-eso-sa")
        else:
            vault_file = paths.vault_dir / "bootstrap.vault.env"
            vault_auth = VaultAuth()
            eso_sa_name = str(getattr(ns, "eso_sa_name", None) or "eso-gsm-reader").strip() or "eso-gsm-reader"
            print(f"generating ESO SA key: {eso_sa_name}@{project_id}.iam.gserviceaccount.com")
            eso_ok, eso_detail = _provision_eso_sa(
                project_id=project_id,
                evidence_dir=evidence_dir,
                vault_file=vault_file,
                vault_auth=vault_auth,
                sa_name=eso_sa_name,
                force=bool(getattr(ns, "force", False)),
            )
            if not eso_ok:
                print(f"ERR: ESO SA key generation failed: {eso_detail}")
                print(f"run record: {evidence_dir}")
                return TARGET_EXEC_FAILURE
            print(f"eso-sa key written to vault: {eso_detail}")
            eso_sa_email = f"{eso_sa_name}@{project_id}.iam.gserviceaccount.com"

    if tfvars_out.exists() and not getattr(ns, "force", False):
        print(f"ERR: credentials file already exists (use --force to overwrite): {tfvars_out}")
        return OPERATOR_ERROR

    try:
        tfvars_out.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            "# <sensitive> Do not commit.\n"
            "# purpose: Terraform runtime inputs for GCP stacks (impersonation-based).\n"
            "# </sensitive>\n\n"
            f'project_id                  = "{project_id}"\n'
            f'region                      = "{region}"\n'
            f'impersonate_service_account = "{terraform_sa_email}"\n'
        )
        tfvars_out.write_text(payload, encoding="utf-8")
        os.chmod(tfvars_out, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        print("ERR: failed to write gcp tfvars output")
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
                    "evidence_dir": str(evidence_dir),
                },
                "context": {
                    "auth_mode": auth_mode,
                    "project_id": project_id,
                    "region": region,
                    "billing_account_id": billing_account_id,
                    "terraform_sa_email": terraform_sa_email,
                    "impersonation_validated": bool(impersonation_validated),
                    "project_access_validated": bool(project_access_validated),
                    "project_bootstrap_pending": bool(project_bootstrap_pending),
                    "ssh_public_key": ssh_public_key,
                    "eso_sa_email": eso_sa_email,
                },
            },
        )
    except Exception:
        print("ERR: failed to write readiness marker")
        return WRITE_FAILURE

    print(f"target={target} status=ready run_id={run_id}")
    print(f"run record: {evidence_dir}")
    print(f"readiness: {paths.meta_dir / f'{target}.ready.json'}")
    print(f"credentials: {tfvars_out}")
    if not ssh_public_key:
        print("WARN: no SSH public key discovered for GCP runtime.")
        print("hint: re-run with --ssh-public-key, set GCP_SSH_PUBLIC_KEY in config/env, or ensure ~/.ssh/id_ed25519.pub exists.")
        print("hint: platform/gcp/platform-vm with ssh_keys_from_init=true will fail until a key is present in gcp.ready.json")

    if bool(getattr(ns, "logout_after", False)):
        # Best-effort cleanup; do not fail init if logout fails.
        run_capture(
            ["gcloud", "auth", "revoke", "--all", "--quiet"],
            evidence_dir=evidence_dir,
            label="gcloud_auth_revoke",
            redact=True,
        )
        run_capture(
            ["gcloud", "auth", "application-default", "revoke", "--quiet"],
            evidence_dir=evidence_dir,
            label="gcloud_adc_revoke",
            redact=True,
        )

    return OK


def _provision_eso_sa(
    *,
    project_id: str,
    evidence_dir: Path,
    vault_file: Path,
    vault_auth: VaultAuth,
    sa_name: str = "eso-gsm-reader",
    force: bool = False,
) -> tuple[bool, str]:
    """Generate a GCP SA key for the ESO service account and persist it to the bootstrap vault.

    Infrastructure prerequisites:
      - Service account {sa_name}@{project_id}.iam.gserviceaccount.com exists with
        roles/secretmanager.secretAccessor bound (applied by org/gcp/gsm-eso-sa).
      - constraints/iam.disableServiceAccountKeyCreation is overridden at project scope
        (applied by _ensure_terraform_sa_project_roles during --with-cli-login).

    Steps:
      1. Skip if HYOPS_GSM_SA_KEY_JSON is already in the vault (unless force=True).
      2. Generate a key JSON to a 0600 temp file.
      3. Write the key JSON to the bootstrap vault as HYOPS_GSM_SA_KEY_JSON.
      4. Delete the temp file unconditionally (in finally block).

    Returns (success, detail) where detail is the SA email on success or an error description on failure.
    """
    sa_email = f"{sa_name}@{project_id}.iam.gserviceaccount.com"

    if not force:
        try:
            existing = read_env(vault_file, vault_auth)
            if existing.get("HYOPS_GSM_SA_KEY_JSON"):
                return True, "HYOPS_GSM_SA_KEY_JSON already present in vault; skipping (use --force to reprovision)"
        except FileNotFoundError:
            pass  # bootstrap vault does not exist yet — proceed to create key
        except Exception as exc:
            # Vault exists but could not be decrypted. Warn and continue so the
            # operator can decide: the key creation will succeed but the vault
            # write may also fail, which will surface as a hard error below.
            print(f"WARN: could not read bootstrap vault to check for existing key: {exc}")
            print("hint: if the vault is locked, run: hyops vault password >/dev/null")

    tmp_key_path = ""
    try:
        fd, tmp_key_path = tempfile.mkstemp(prefix="hyops.eso-sa-key.", suffix=".json")
        os.close(fd)
        os.chmod(tmp_key_path, 0o600)

        r = run_capture(
            [
                "gcloud", "iam", "service-accounts", "keys", "create", tmp_key_path,
                "--iam-account", sa_email,
                "--project", project_id,
            ],
            evidence_dir=evidence_dir,
            label="eso_sa_create_key",
            redact=True,
        )
        if r.rc != 0:
            return False, (
                f"failed to create key for {sa_email}: {_first_nonempty_line(r.stderr)}\n"
                "hint: ensure org/gcp/gsm-eso-sa has been applied for this project."
            )

        try:
            key_json = Path(tmp_key_path).read_text(encoding="utf-8").strip()
        except Exception as exc:
            return False, f"failed to read key JSON from temp file: {exc}"

        if not key_json:
            return False, "key JSON was empty after creation"

        try:
            vault_file.parent.mkdir(parents=True, exist_ok=True)
            merge_set(vault_file, vault_auth, {"HYOPS_GSM_SA_KEY_JSON": key_json})
        except Exception as exc:
            return False, f"failed to write HYOPS_GSM_SA_KEY_JSON to bootstrap vault: {exc}"

        return True, sa_email

    finally:
        if tmp_key_path:
            try:
                os.unlink(tmp_key_path)
            except FileNotFoundError:
                pass


def _ensure_org_policy_admin(*, account: str, evidence_dir: Path) -> None:
    """Ensure the operator account holds roles/orgpolicy.policyAdmin on the GCP org.

    This role is a prerequisite for _ensure_terraform_sa_project_roles, which
    sets the project-level iam.disableServiceAccountKeyCreation override using
    operator ADC. roles/orgpolicy.policyAdmin is only bindable at the org scope,
    not at the project scope, so it cannot be managed by the Terraform SA.

    The grant relies on the account's existing roles/resourcemanager.organizationAdmin
    binding (which includes resourcemanager.organizations.setIamPolicy).

    Non-fatal: if no org is found, the account already holds the role, or the
    grant fails for any reason, a warning is printed and init continues.
    Only runs during interactive operator bootstrap (--with-cli-login).
    """
    org_id = _first_nonempty_line(
        _cmd_stdout(
            ["gcloud", "organizations", "list", "--format=value(ID)"],
            evidence_dir,
            "org_list_for_orgpolicy_admin",
        )
    ).strip()
    if not org_id:
        return  # no org — nothing to do (personal project, no org constraint)

    # Check whether the role is already present to avoid a redundant write.
    existing = _cmd_stdout(
        [
            "gcloud", "organizations", "get-iam-policy", org_id,
            f"--filter=bindings.role=roles/orgpolicy.policyAdmin AND bindings.members:user:{account}",
            "--format=value(bindings.role)",
            "--flatten=bindings",
        ],
        evidence_dir,
        "org_orgpolicy_admin_check",
    ).strip()
    if existing:
        return  # already holds the role

    r = run_capture(
        [
            "gcloud", "organizations", "add-iam-policy-binding", org_id,
            f"--member=user:{account}",
            "--role=roles/orgpolicy.policyAdmin",
            "--condition=None",
        ],
        evidence_dir=evidence_dir,
        label="org_grant_orgpolicy_admin",
        redact=True,
    )
    if r.rc != 0:
        print(
            f"WARN: could not grant roles/orgpolicy.policyAdmin to {account} on org {org_id}; "
            "org/gcp/gsm-eso-sa may require a manual grant if the org policy constraint is enforced. "
            f"detail: {_first_nonempty_line(r.stderr)}"
        )
    else:
        print(f"org-policy-admin: granted roles/orgpolicy.policyAdmin to {account} on org {org_id}")


def _require_tty() -> bool:
    return os.isatty(0) and os.isatty(1)


def _run_interactive_adc_login(evidence_dir: Path, *, reason: str) -> bool:
    if not _require_tty():
        print("ERR: interactive authentication requires a TTY")
        print(f"run record: {evidence_dir}")
        return False
    print(f"WARN: {reason}")
    print("starting interactive ADC login; follow the prompts shown below.")
    r = run_capture_interactive(
        ["gcloud", "auth", "application-default", "login", "--no-launch-browser"],
        evidence_dir=evidence_dir,
        label="adc_login",
        redact=True,
    )
    if r.rc != 0:
        print("ERR: ADC login failed; see run record")
        print(f"run record: {evidence_dir}")
        return False
    return True


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


def _terraform_sa_from_state(state_dir: Path) -> str:
    """Best-effort: infer the Terraform runtime service account email from module state.

    This breaks the initial bootstrap loop:
      1) init gcp (no SA email yet) -> allow project-factory apply
      2) apply org/gcp/project-factory -> writes SA email to state
      3) re-run init gcp -> auto-populates impersonation target
    """

    try:
        st = read_module_state(state_dir, "org/gcp/project-factory")
    except FileNotFoundError:
        return ""
    except Exception:
        return ""

    outputs = st.get("outputs")
    if not isinstance(outputs, dict):
        return ""

    for key in (
        "terraform_sa_email",
        "terraform_service_account_email",
        "terraform_service_account",
        "service_account_email",
    ):
        v = outputs.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            email = v.get("email")
            if isinstance(email, str) and email.strip():
                return email.strip()

    return ""


def _bootstrap_impersonation_grant(
    *,
    active_account: str,
    project_id: str,
    terraform_sa_email: str,
    evidence_dir: Path,
) -> bool:
    if not active_account or not project_id or not terraform_sa_email:
        return False
    member = f"user:{active_account}"
    print("note: attempting bootstrap impersonation setup for the derived Terraform service account.")
    enable = run_capture(
        [
            "gcloud",
            "services",
            "enable",
            "iamcredentials.googleapis.com",
            "--project",
            project_id,
        ],
        evidence_dir=evidence_dir,
        label="enable_iamcredentials_api",
        redact=True,
    )
    if enable.rc != 0:
        return False
    grant = run_capture(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "add-iam-policy-binding",
            terraform_sa_email,
            "--project",
            project_id,
            "--member",
            member,
            "--role",
            "roles/iam.serviceAccountTokenCreator",
        ],
        evidence_dir=evidence_dir,
        label="grant_token_creator_on_terraform_sa",
        redact=True,
    )
    return grant.rc == 0


def _ensure_terraform_sa_project_roles(
    *,
    project_id: str,
    terraform_sa_email: str,
    evidence_dir: Path,
) -> None:
    """Ensure the Terraform runtime SA holds the project-level roles required to run all hyops modules.

    Runs as operator ADC (not impersonation) during --with-cli-login bootstrap.
    All gcloud operations are idempotent: re-running produces the same state.

    APIs enabled:
      orgpolicy.googleapis.com       — required for `gcloud resource-manager org-policies` calls
      secretmanager.googleapis.com   — required for Secret Manager resources

    Org policy applied (project scope):
      constraints/iam.disableServiceAccountKeyCreation set to not enforced — allows
      `hyops init gcp --with-eso-sa` to generate the ESO reader SA key. The policy
      is applied here via ADC because roles/orgpolicy.policyAdmin is not bindable
      at project resource scope and cannot be delegated to the Terraform SA.

    Roles granted to the Terraform SA:
      roles/editor                          — resource creation and management across GCP services
      roles/resourcemanager.projectIamAdmin — bind IAM roles at project scope
      roles/secretmanager.admin             — create and manage secrets in Secret Manager
      roles/servicenetworking.networksAdmin — create private service networking peerings on the project VPC

    Note: roles/orgpolicy.policyAdmin is org-scoped only. It is granted to the
    operator account in _ensure_org_policy_admin, not to the Terraform SA.
    """
    if not project_id or not terraform_sa_email:
        return

    member = f"serviceAccount:{terraform_sa_email}"

    apis = [
        "orgpolicy.googleapis.com",
        "secretmanager.googleapis.com",
    ]
    for api in apis:
        r = run_capture(
            ["gcloud", "services", "enable", api, "--project", project_id],
            evidence_dir=evidence_dir,
            label=f"enable_api_{api.replace('.', '_')}",
            redact=True,
        )
        if r.rc == 0:
            print(f"terraform-sa-setup: ensured {api} is enabled")
        else:
            print(
                f"WARN: could not enable {api} on {project_id}; "
                f"downstream modules may fail. detail: {_first_nonempty_line(r.stderr)}"
            )

    # Lift the org-level iam.disableServiceAccountKeyCreation constraint at
    # project scope. This allows `hyops init gcp --with-eso-sa` to generate a
    # key for the ESO reader SA. roles/orgpolicy.policyAdmin is not bindable at
    # project resource scope, so this is done here via ADC (which holds the role
    # at org scope) rather than via Terraform impersonation.
    policy_file: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as tf_pol:
            tf_pol.write(
                "constraint: constraints/iam.disableServiceAccountKeyCreation\n"
                "booleanPolicy:\n"
                "  enforced: false\n"
            )
            policy_file = tf_pol.name
        r = run_capture(
            [
                "gcloud", "resource-manager", "org-policies", "set-policy",
                policy_file,
                "--project", project_id,
            ],
            evidence_dir=evidence_dir,
            label="project_allow_sa_key_creation",
            redact=True,
        )
        if r.rc == 0:
            print(f"terraform-sa-setup: ensured iam.disableServiceAccountKeyCreation is not enforced on {project_id}")
        else:
            print(
                f"WARN: could not lift iam.disableServiceAccountKeyCreation on {project_id}; "
                f"--with-eso-sa may fail. detail: {_first_nonempty_line(r.stderr)}"
            )
    finally:
        if policy_file:
            try:
                os.unlink(policy_file)
            except FileNotFoundError:
                pass

    roles = [
        "roles/editor",
        "roles/resourcemanager.projectIamAdmin",
        "roles/secretmanager.admin",
        "roles/servicenetworking.networksAdmin",
    ]
    for role in roles:
        r = run_capture(
            [
                "gcloud", "projects", "add-iam-policy-binding", project_id,
                f"--member={member}",
                f"--role={role}",
            ],
            evidence_dir=evidence_dir,
            label=f"grant_terraform_sa_{role.replace('/', '_').replace('.', '_')}",
            redact=True,
        )
        if r.rc == 0:
            print(f"terraform-sa-setup: ensured {role} on {terraform_sa_email}")
        else:
            print(
                f"WARN: could not ensure {role} on {terraform_sa_email} for project {project_id}; "
                f"detail: {_first_nonempty_line(r.stderr)}"
            )


def _write_config_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# GCP init configuration (non-secret)\n"
        "GCP_PROJECT_ID=\n"
        "GCP_REGION=\n"
        "# Optional: billing account id for org/gcp/project-factory when creating new projects.\n"
        "GCP_BILLING_ACCOUNT_ID=\n"
        "# Optional (recommended): Terraform runtime SA email (impersonation target).\n"
        "# If omitted, HybridOps can derive it from org/gcp/project-factory state after apply.\n"
        "GCP_TERRAFORM_SA_EMAIL=\n"
        "GCP_ADC_QUOTA_PROJECT_ID=\n"
        "# Optional non-secret public key persisted into gcp.ready.json for GCE runner/VM bootstrap.\n"
        "GCP_SSH_PUBLIC_KEY=\n"
        "GCP_TFVARS_OUT=\n"
    )
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _ensure_gcp_config_keys(path: Path) -> bool:
    existing = read_kv_file(path)
    missing: dict[str, str] = {}
    for key in (
        "GCP_PROJECT_ID",
        "GCP_REGION",
        "GCP_BILLING_ACCOUNT_ID",
        "GCP_TERRAFORM_SA_EMAIL",
        "GCP_ADC_QUOTA_PROJECT_ID",
        "GCP_SSH_PUBLIC_KEY",
        "GCP_TFVARS_OUT",
    ):
        if key not in existing:
            missing[key] = ""
    if not missing:
        return False
    _upsert_kv_file(path, missing)
    return True


def _upsert_kv_file(path: Path, updates: dict[str, str]) -> None:
    if not updates:
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    pending = {str(k): str(v) for k, v in updates.items() if str(k).strip()}
    out: list[str] = []
    for raw in lines:
        replaced = False
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, _sep, _value = raw.partition("=")
            key = key.strip()
            if key in pending:
                out.append(f"{key}={pending.pop(key)}")
                replaced = True
        if not replaced:
            out.append(raw)
    if pending:
        if out and out[-1].strip():
            out.append("")
        for key, value in pending.items():
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _discover_open_billing_accounts(evidence_dir: Path) -> list[dict[str, str]]:
    for argv, label in (
        (["gcloud", "billing", "accounts", "list", "--format=json"], "gcloud_billing_accounts_list"),
        (["gcloud", "beta", "billing", "accounts", "list", "--format=json"], "gcloud_beta_billing_accounts_list"),
    ):
        raw = _cmd_stdout(argv, evidence_dir, label)
        if not raw.strip():
            continue
        try:
            items = json.loads(raw)
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        out: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            open_flag = item.get("open")
            if open_flag is False:
                continue
            name = normalize_billing_account_id(str(item.get("name") or "").strip())
            display_name = str(item.get("displayName") or item.get("display_name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "id": name,
                    "display_name": display_name,
                }
            )
        if out:
            return out
    return []


def _select_billing_account_interactive(accounts: list[dict[str, str]]) -> tuple[str, str]:
    if len(accounts) == 1:
        choice = str(accounts[0].get("id") or "").strip()
        label = str(accounts[0].get("display_name") or "").strip()
        if choice:
            if label:
                print(f"selected billing account: {label} ({choice})")
            else:
                print(f"selected billing account: {choice}")
            return choice, "gcloud"

    if accounts:
        print("available billing accounts:")
        for idx, item in enumerate(accounts, start=1):
            acc_id = str(item.get("id") or "").strip()
            label = str(item.get("display_name") or "").strip()
            suffix = f" ({acc_id})" if label else ""
            print(f"  {idx}. {label or acc_id}{suffix}")
        prompt = "Billing account [number, id, or blank to skip]: "
    else:
        print("note: no open billing accounts were auto-discovered from gcloud.")
        prompt = "Billing account id (blank to skip): "

    try:
        answer = str(input(prompt) or "").strip()
    except EOFError:
        return "", ""
    except KeyboardInterrupt:
        print()
        return "", ""
    if not answer:
        return "", ""
    if answer.isdigit():
        idx = int(answer)
        if 1 <= idx <= len(accounts):
            return str(accounts[idx - 1].get("id") or "").strip(), "prompt"
    return answer, "prompt"


def _review_detected_gcp_defaults_interactive(
    *,
    env_name: str,
    project_id: str,
    project_id_source: str,
    region: str,
    region_source: str,
    billing_account_id: str,
    billing_account_source: str,
) -> tuple[str, str, str]:
    label = env_name or "<env>"
    print(f"review detected GCP defaults for env {label}:")
    if project_id:
        print(f"  project_id: {project_id} (source={project_id_source})")
    if region:
        print(f"  region: {region} (source={region_source})")
    if billing_account_id:
        print(f"  billing_account_id: {billing_account_id} (source={billing_account_source})")
    print("press Enter to keep a detected value, or type a replacement.")

    try:
        project_ans = str(input(f"GCP project id [{project_id}]: ") or "").strip()
    except EOFError:
        project_ans = ""
    except KeyboardInterrupt:
        print()
        return project_id, region, billing_account_id
    if project_ans:
        project_id = project_ans

    try:
        region_ans = str(input(f"GCP region [{region}]: ") or "").strip()
    except EOFError:
        region_ans = ""
    except KeyboardInterrupt:
        print()
        return project_id, region, billing_account_id
    if region_ans:
        region = region_ans

    billing_prompt_default = billing_account_id or ""
    try:
        billing_ans = str(input(f"Billing account id [{billing_prompt_default}]: ") or "").strip()
    except EOFError:
        billing_ans = ""
    except KeyboardInterrupt:
        print()
        return project_id, region, billing_account_id
    if billing_ans:
        billing_account_id = billing_ans

    return project_id, region, billing_account_id


def _diagnose_gcp_project_access(project_id: str, evidence_dir: Path) -> tuple[bool, str]:
    project_id = str(project_id or "").strip()
    if not project_id:
        return False, "missing project id"
    r = run_capture(
        ["gcloud", "projects", "describe", project_id, "--format=value(projectId)"],
        evidence_dir=evidence_dir,
        label="gcloud_project_access_check",
        redact=True,
    )
    if r.rc == 0 and _first_nonempty_line(r.stdout) == project_id:
        return True, ""
    detail = _first_nonempty_line(r.stderr) or _first_nonempty_line(r.stdout) or "project access check failed"
    return False, detail


def _format_project_access_hint(project_id: str, detail: str) -> str:
    base = (
        f"hint: project '{project_id}' may belong to another Google account or organization, "
        "or your current identity may no longer have IAM access."
    )
    if detail:
        return f"{base}\ndetail: {detail}"
    return base


def _cmd_ok(argv: list[str], evidence_dir: Path, label: str) -> bool:
    r = run_capture(argv, evidence_dir=evidence_dir, label=label, redact=True)
    return r.rc == 0


def _cmd_stdout(argv: list[str], evidence_dir: Path, label: str) -> str:
    r = run_capture(argv, evidence_dir=evidence_dir, label=label, redact=True)
    if r.rc != 0:
        return ""
    return (r.stdout or "").strip()


def _shell_ok(cmd: str, evidence_dir: Path, label: str) -> bool:
    r = run_capture(["/bin/bash", "-lc", cmd], evidence_dir=evidence_dir, label=label, redact=True)
    return r.rc == 0


def _first_nonempty_line(text: str) -> str:
    for raw in (text or "").splitlines():
        line = str(raw or "").strip()
        if line:
            return line
    return ""


def _normalize_gcloud_value(text: str) -> str:
    value = _first_nonempty_line(text)
    if value in {"(unset)", "None", "null"}:
        return ""
    return value


def _region_from_zone(zone: str) -> str:
    parts = [part for part in str(zone or "").strip().split("-") if part]
    if len(parts) < 3:
        return ""
    return "-".join(parts[:-1])
