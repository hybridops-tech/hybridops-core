"""
purpose: Initialise GCP target runtime inputs using ADC + service account impersonation.
Architecture Decision: ADR-N/A
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import os
import shlex
import stat
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
from hyops.runtime.paths import RuntimePaths
from hyops.runtime.proc import run_capture
from hyops.runtime.readiness import write_marker
from hyops.runtime.root import resolve_runtime_root
from hyops.runtime.state import write_json
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.module_state import read_module_state


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser(
        "gcp",
        help="Initialise GCP runtime inputs and prerequisites.",
        epilog=(
            "Notes:\n"
            "  - Shared flags live on `hyops init` (e.g. --root, --out-dir, --config, --dry-run).\n"
            "  - Required config keys: GCP_PROJECT_ID, GCP_REGION.\n"
            "  - Optional: GCP_TERRAFORM_SA_EMAIL (recommended for steady-state; can be derived from project-factory state).\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    add_init_shared_args(p)

    p.add_argument("--project-id", default=None, help="Override GCP project id.")
    p.add_argument("--region", default=None, help="Override GCP region.")
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
        print("edit the file and re-run: hyops init gcp")
        return CONFIG_TEMPLATE_WRITTEN

    cfg = read_kv_file(config_path)

    project_id = (
        getattr(ns, "project_id", None)
        or os.environ.get("GCP_PROJECT_ID")
        or cfg.get("GCP_PROJECT_ID")
        or ""
    ).strip()
    region = (
        getattr(ns, "region", None)
        or os.environ.get("GCP_REGION")
        or cfg.get("GCP_REGION")
        or ""
    ).strip()
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

    if not project_id or not region:
        print(
            f"ERR: required config missing in {config_path} "
            f"(GCP_PROJECT_ID, GCP_REGION)"
        )
        print(f"evidence: {evidence_dir}")
        return OPERATOR_ERROR

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
                "terraform_sa_email": terraform_sa_email,
                "adc_quota_project_id": adc_quota_project_id,
                "ssh_public_key_present": bool(ssh_public_key),
            },
        },
    )

    if getattr(ns, "dry_run", False):
        print("dry-run: would validate gcloud + adc (and impersonation when configured), then write tfvars + readiness")
        print(f"evidence: {evidence_dir}")
        return OK

    if os.environ.get("CI") and not getattr(ns, "non_interactive", False):
        print("ERR: interactive gcp init must not run in CI (use --non-interactive)")
        return OPERATOR_ERROR

    if not _cmd_ok(["gcloud", "--version"], evidence_dir, "gcloud_version"):
        print("ERR: gcloud not available; install with: hyops setup cloud-gcp --sudo")
        print(f"evidence: {evidence_dir}")
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
                    print("ERR: failed to activate service account from GOOGLE_APPLICATION_CREDENTIALS; see evidence")
                    print(f"evidence: {evidence_dir}")
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
                print(f"evidence: {evidence_dir}")
                return OPERATOR_ERROR
        else:
            if not bool(getattr(ns, "with_cli_login", False)):
                print("ERR: gcloud auth is required (no active account).")
                print("Option A: run `gcloud auth login` (workstations) then re-run: hyops init gcp")
                print("Option B: run `gcloud auth activate-service-account --key-file <path>` (CI/runners)")
                print("Option C: re-run with: hyops init gcp --with-cli-login")
                print(f"evidence: {evidence_dir}")
                return OPERATOR_ERROR

            if not _require_tty():
                print("ERR: interactive authentication requires a TTY")
                print(f"evidence: {evidence_dir}")
                return OPERATOR_ERROR

            r = run_capture(
                ["gcloud", "auth", "login", "--no-launch-browser"],
                evidence_dir=evidence_dir,
                label="gcloud_auth_login",
                redact=True,
            )
            if r.rc != 0:
                print("ERR: gcloud auth login failed; see evidence")
                print(f"evidence: {evidence_dir}")
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
                print(f"evidence: {evidence_dir}")
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
            print(f"evidence: {evidence_dir}")
            return OPERATOR_ERROR
        if not bool(getattr(ns, "with_cli_login", False)):
            print("ERR: ADC not available.")
            print("Run: gcloud auth application-default login")
            print("Then re-run: hyops init gcp")
            print(f"evidence: {evidence_dir}")
            return OPERATOR_ERROR
        if not _require_tty():
            print("ERR: interactive authentication requires a TTY")
            print(f"evidence: {evidence_dir}")
            return OPERATOR_ERROR
        r = run_capture(
            ["gcloud", "auth", "application-default", "login", "--no-launch-browser"],
            evidence_dir=evidence_dir,
            label="adc_login",
            redact=True,
        )
        if r.rc != 0:
            print("ERR: ADC login failed; see evidence")
            print(f"evidence: {evidence_dir}")
            return TARGET_EXEC_FAILURE

    if adc_quota_project_id:
        run_capture(
            ["gcloud", "auth", "application-default", "set-quota-project", adc_quota_project_id],
            evidence_dir=evidence_dir,
            label="adc_set_quota_project",
            redact=True,
        )

    impersonation_validated = False
    if not terraform_sa_email:
        if non_interactive:
            print("ERR: GCP_TERRAFORM_SA_EMAIL is required in --non-interactive mode")
            print("hint: set it in <root>/config/gcp.conf or export GCP_TERRAFORM_SA_EMAIL, then re-run.")
            print("hint: if you're bootstrapping a new project, run org/gcp/project-factory first, then re-run init.")
            print(f"evidence: {evidence_dir}")
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
        if not imp_ok:
            if not terraform_sa_email_explicit:
                print("WARN: derived Terraform service account failed impersonation validation; continuing without impersonation.")
                print(
                    "hint: set GCP_TERRAFORM_SA_EMAIL explicitly once caller permissions are correct, "
                    "or keep using direct ADC for this environment."
                )
                print(f"evidence: {evidence_dir}")
                terraform_sa_email = ""
            else:
                print("ERR: impersonation validation failed; see evidence")
                print("hint: caller must have roles/iam.serviceAccountTokenCreator on the target service account.")
                print("hint: ensure iamcredentials.googleapis.com is enabled in the target project.")
                print(f"evidence: {evidence_dir}")
                return TARGET_EXEC_FAILURE
        impersonation_validated = bool(terraform_sa_email)

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
                    "project_id": project_id,
                    "region": region,
                    "terraform_sa_email": terraform_sa_email,
                    "impersonation_validated": bool(impersonation_validated),
                    "ssh_public_key": ssh_public_key,
                },
            },
        )
    except Exception:
        print("ERR: failed to write readiness marker")
        return WRITE_FAILURE

    print(f"target={target} status=ready run_id={run_id}")
    print(f"evidence: {evidence_dir}")
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


def _require_tty() -> bool:
    return os.isatty(0) and os.isatty(1)


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


def _write_config_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# GCP init configuration (non-secret)\n"
        "GCP_PROJECT_ID=\n"
        "GCP_REGION=\n"
        "# Optional (recommended): Terraform runtime SA email (impersonation target).\n"
        "# If omitted, HyOps can derive it from org/gcp/project-factory state after apply.\n"
        "GCP_TERRAFORM_SA_EMAIL=\n"
        "GCP_ADC_QUOTA_PROJECT_ID=\n"
        "# Optional non-secret public key persisted into gcp.ready.json for GCE runner/VM bootstrap.\n"
        "GCP_SSH_PUBLIC_KEY=\n"
        "GCP_TFVARS_OUT=\n"
    )
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


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
