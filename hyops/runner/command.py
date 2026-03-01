"""Runner execution-plane CLI commands."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id
from hyops.runtime.exitcodes import OPERATOR_ERROR
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_state import normalize_module_state_ref, read_module_state
from hyops.runtime.module_state_contracts import resolve_inventory_groups_from_state
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.proc import run_capture_stream
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.terraform_cloud import (
    read_tfrc_token,
    resolve_config as resolve_tfc_config,
    runtime_config_path as tfc_runtime_config_path,
    tf_token_env_key,
)
from hyops.runtime.vault import VaultAuth, read_env
from hyops.secrets.command import (
    resolve_default_gsm_map_file,
    resolve_gsm_project_id,
    sync_gsm_to_runtime,
    resolve_default_hashicorp_vault_map_file,
    sync_hashicorp_vault_to_runtime,
)

_SYNC_DIRS = ("config", "credentials", "vault", "state", "meta", "artifacts")
_RETURN_DIRS = ("config", "state", "logs", "meta", "artifacts")


@dataclass(frozen=True)
class RunnerContext:
    state_ref: str
    vm_key: str
    target_user: str
    target_port: int
    ssh_private_key_file: str
    ssh_access_mode: str
    ssh_proxy_jump_host: str
    ssh_proxy_jump_user: str
    ssh_proxy_jump_port: int
    gcp_iap_instance: str
    gcp_iap_project_id: str
    gcp_iap_zone: str
    host: str
    install_prefix: str

    @property
    def remote_host(self) -> str:
        if self.ssh_access_mode == "gcp-iap" and self.gcp_iap_instance:
            return self.gcp_iap_instance
        return self.host

    @property
    def remote_hyops(self) -> str:
        return str((Path(self.install_prefix) / "venv" / "bin" / "hyops").as_posix())

    @property
    def remote_core_root(self) -> str:
        return str((Path(self.install_prefix) / "app").as_posix())


def add_runner_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("runner", help="Execution-plane dispatch via a prepared ops runner.")
    ssp = p.add_subparsers(dest="runner_cmd", required=True)

    b = ssp.add_parser("blueprint", help="Execute blueprint commands from a prepared runner.")
    bssp = b.add_subparsers(dest="runner_blueprint_cmd", required=True)

    def add_common_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--root", default=None, help="Override runtime root.")
        sub.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
        sub.add_argument(
            "--runner-state-ref",
            required=True,
            help=(
                "platform/linux/ops-runner state ref for the prepared runner, "
                "e.g. platform/linux/ops-runner#gcp_ops_runner_bootstrap"
            ),
        )
        sub.add_argument(
            "--runner-vm-key",
            default="",
            help="Optional VM key when the resolved runner inventory contains more than one runner host.",
        )
        sub.add_argument(
            "--file",
            required=True,
            help="Env-scoped blueprint overlay file under <runtime>/config/blueprints/.",
        )
        sub.add_argument(
            "--keep-remote-job",
            action="store_true",
            help="Do not remove the temporary runner job directory after execution.",
        )
        sub.add_argument(
            "--sync-env",
            action="append",
            default=[],
            help="Repeatable local env var key to export into the remote hyops process for this dispatch only.",
        )
        sub.add_argument(
            "--secret-source",
            choices=["runtime", "vault", "gsm"],
            default="runtime",
            help="Optional pre-dispatch secret authority used to refresh the runtime vault (default: runtime).",
        )
        sub.add_argument(
            "--secret-scope",
            default="all",
            help="Secret sync scope used when --secret-source=vault (default: all).",
        )
        sub.add_argument(
            "--secret-map-file",
            default=None,
            help="Optional map file for external secret sync before dispatch.",
        )
        sub.add_argument(
            "--vault-addr",
            default=None,
            help="HashiCorp Vault address used when --secret-source=vault (or set VAULT_ADDR).",
        )
        sub.add_argument(
            "--vault-token-env",
            default="VAULT_TOKEN",
            help="Env var carrying the HashiCorp Vault token when --secret-source=vault (default: VAULT_TOKEN).",
        )
        sub.add_argument(
            "--vault-namespace",
            default=None,
            help="Optional HashiCorp Vault namespace when --secret-source=vault (or set VAULT_NAMESPACE).",
        )
        sub.add_argument(
            "--vault-engine",
            choices=["kv-v1", "kv-v2"],
            default="kv-v2",
            help="HashiCorp Vault KV engine mode when --secret-source=vault (default: kv-v2).",
        )
        sub.add_argument(
            "--gsm-project-id",
            default=None,
            help="Override GCP project id when --secret-source=gsm (default: gcp init config or GCP_PROJECT_ID).",
        )
        sub.add_argument(
            "--gsm-project-state-ref",
            default=None,
            help="Optional module state ref that publishes outputs.project_id when --secret-source=gsm.",
        )

    pre = bssp.add_parser("preflight", help="Run blueprint preflight from the selected runner.")
    add_common_args(pre)
    pre.set_defaults(_handler=run_runner_blueprint_preflight)

    dep = bssp.add_parser("deploy", help="Run blueprint deploy from the selected runner.")
    add_common_args(dep)
    dep.add_argument("--execute", action="store_true", help="Execute ordered blueprint steps.")
    dep.add_argument("--skip-preflight", action="store_true", help="Skip blueprint-level preflight gate.")
    dep.add_argument("--yes", action="store_true", help="Proceed without interactive confirmation.")
    dep.set_defaults(_handler=run_runner_blueprint_deploy)


def _enforce_runtime_blueprint_file_scope(file_path: str, *, allowed_root: Path) -> Path:
    candidate = Path(str(file_path or "")).expanduser().resolve()
    try:
        candidate.relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"runner blueprint execution requires --file to live under {allowed_root.resolve()}. "
            "Use `hyops blueprint init` to materialize an env-scoped overlay first."
        ) from exc
    return candidate


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    return payload


def _pick_runner_host(runner_hosts: list[dict[str, Any]], *, runner_vm_key: str) -> dict[str, Any]:
    if runner_vm_key:
        for item in runner_hosts:
            if str(item.get("name") or "").strip() == runner_vm_key:
                return item
        raise ValueError(
            f"--runner-vm-key={runner_vm_key!r} was not found in resolved runner inventory"
        )
    if len(runner_hosts) != 1:
        names = ", ".join(
            sorted(
                str(item.get("name") or "").strip()
                for item in runner_hosts
                if str(item.get("name") or "").strip()
            )
        )
        raise ValueError(
            "runner inventory resolved more than one host. "
            f"Set --runner-vm-key explicitly. Available: {names or 'unknown'}"
        )
    return runner_hosts[0]


def _resolve_runner_context(paths, *, runner_state_ref: str, runner_vm_key: str) -> RunnerContext:
    normalized = normalize_module_state_ref(runner_state_ref)
    state = read_module_state(paths.state_dir, normalized)
    status = str(state.get("status") or "").strip().lower()
    if status != "ok":
        raise ValueError(f"runner_state_ref={normalized} is not ready (status={status or 'missing'})")

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}
    if str(outputs.get("cap.ctrl.runner") or "").strip().lower() != "ready":
        raise ValueError(f"runner_state_ref={normalized} does not publish cap.ctrl.runner=ready")

    rerun_inputs_path = str(state.get("rerun_inputs_file") or "").strip()
    if not rerun_inputs_path:
        raise ValueError(f"runner_state_ref={normalized} does not publish rerun_inputs_file")
    rerun_inputs = _load_yaml_mapping(Path(rerun_inputs_path).expanduser().resolve())

    input_contract = state.get("input_contract")
    if not isinstance(input_contract, dict):
        input_contract = {}
    inventory_state_ref = str(
        input_contract.get("inventory_state_ref") or rerun_inputs.get("inventory_state_ref") or ""
    ).strip()
    if not inventory_state_ref:
        raise ValueError(f"runner_state_ref={normalized} does not publish an inventory_state_ref")

    resolved_inputs = dict(rerun_inputs)
    resolved_inputs["inventory_state_ref"] = inventory_state_ref
    resolve_inventory_groups_from_state(resolved_inputs, state_root=paths.state_dir)
    inventory_groups = resolved_inputs.get("inventory_groups")
    if not isinstance(inventory_groups, dict):
        raise ValueError("resolved runner inventory_groups is not a mapping")
    runner_hosts = inventory_groups.get("runner")
    if not isinstance(runner_hosts, list) or not runner_hosts:
        raise ValueError("resolved runner inventory must include group 'runner' with at least one host")
    selected = _pick_runner_host(runner_hosts, runner_vm_key=runner_vm_key)

    key_path = str(resolved_inputs.get("ssh_private_key_file") or "").strip()
    if key_path:
        expanded = Path(key_path).expanduser().resolve()
        if not expanded.exists():
            raise ValueError(f"runner ssh_private_key_file not found: {expanded}")
        key_path = str(expanded)

    return RunnerContext(
        state_ref=normalized,
        vm_key=str(selected.get("name") or "").strip() or runner_vm_key,
        target_user=str(resolved_inputs.get("target_user") or "opsadmin").strip() or "opsadmin",
        target_port=int(resolved_inputs.get("target_port") or 22),
        ssh_private_key_file=key_path,
        ssh_access_mode=str(resolved_inputs.get("ssh_access_mode") or "direct").strip().lower() or "direct",
        ssh_proxy_jump_host=str(resolved_inputs.get("ssh_proxy_jump_host") or "").strip(),
        ssh_proxy_jump_user=str(resolved_inputs.get("ssh_proxy_jump_user") or "root").strip() or "root",
        ssh_proxy_jump_port=int(resolved_inputs.get("ssh_proxy_jump_port") or 22),
        gcp_iap_instance=str(selected.get("gcp_iap_instance") or resolved_inputs.get("gcp_iap_instance") or "").strip(),
        gcp_iap_project_id=str(selected.get("gcp_iap_project_id") or resolved_inputs.get("gcp_iap_project_id") or "").strip(),
        gcp_iap_zone=str(selected.get("gcp_iap_zone") or resolved_inputs.get("gcp_iap_zone") or "").strip(),
        host=str(selected.get("host") or selected.get("ansible_host") or "").strip(),
        install_prefix=str(outputs.get("runner_install_prefix") or "/opt/hybridops/core").strip()
        or "/opt/hybridops/core",
    )


def _ssh_common_argv(ctx: RunnerContext) -> list[str]:
    argv = [
        "-p",
        str(int(ctx.target_port)),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    if ctx.ssh_private_key_file:
        argv.extend(["-i", ctx.ssh_private_key_file])
    if ctx.ssh_access_mode == "bastion-explicit":
        if not ctx.ssh_proxy_jump_host:
            raise ValueError("runner ssh_access_mode=bastion-explicit requires ssh_proxy_jump_host")
        proxy_parts = [
            "ssh",
            "-p",
            str(int(ctx.ssh_proxy_jump_port)),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
        if ctx.ssh_private_key_file:
            proxy_parts.extend(["-i", ctx.ssh_private_key_file])
        proxy_parts.append(f"{ctx.ssh_proxy_jump_user}@{ctx.ssh_proxy_jump_host}")
        proxy_parts.extend(["nc", "%h", "%p"])
        argv.extend(["-o", f"ProxyCommand={' '.join(proxy_parts)}"])
    elif ctx.ssh_access_mode == "gcp-iap":
        if not (ctx.gcp_iap_instance and ctx.gcp_iap_project_id and ctx.gcp_iap_zone):
            raise ValueError(
                "runner ssh_access_mode=gcp-iap requires gcp_iap_instance, gcp_iap_project_id, and gcp_iap_zone"
            )
        gcloud_bin = shutil.which("gcloud")
        if not gcloud_bin:
            raise ValueError("gcloud is required for runner ssh_access_mode=gcp-iap")
        proxy_cmd = (
            f"{shlex.quote(gcloud_bin)} compute start-iap-tunnel {shlex.quote(ctx.gcp_iap_instance)} %p "
            f"--listen-on-stdin --project {shlex.quote(ctx.gcp_iap_project_id)} "
            f"--zone {shlex.quote(ctx.gcp_iap_zone)} --verbosity=warning"
        )
        argv.extend(["-o", f"ProxyCommand={proxy_cmd}"])
    return argv


def _remote_spec(ctx: RunnerContext) -> str:
    return f"{ctx.target_user}@{ctx.remote_host}"


def _ssh_argv(ctx: RunnerContext, remote_command: str) -> list[str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        raise ValueError("missing command: ssh")
    return [ssh_bin, *_ssh_common_argv(ctx), _remote_spec(ctx), remote_command]


def _scp_argv(ctx: RunnerContext, src: str, dest: str, *, to_remote: bool) -> list[str]:
    scp_bin = shutil.which("scp")
    if not scp_bin:
        raise ValueError("missing command: scp")
    common = _ssh_common_argv(ctx)
    scp_args: list[str] = []
    idx = 0
    while idx < len(common):
        token = common[idx]
        if token == "-p":
            scp_args.extend(["-P", common[idx + 1]])
            idx += 2
            continue
        scp_args.append(token)
        idx += 1
    remote = f"{_remote_spec(ctx)}:{dest}"
    if to_remote:
        return [scp_bin, *scp_args, src, remote]
    return [scp_bin, *scp_args, remote, src]


def _bundle_runtime(paths, bundle_path: Path) -> None:
    with tarfile.open(bundle_path, "w:gz") as tf:
        for name in _SYNC_DIRS:
            src = paths.root / name
            if not src.exists():
                continue
            tf.add(src, arcname=name)


def _safe_extract_archive(archive_path: Path, dest_root: Path) -> None:
    dest_root = dest_root.resolve()
    with tarfile.open(archive_path, "r:gz") as tf:
        for member in tf.getmembers():
            member_path = (dest_root / member.name).resolve()
            try:
                member_path.relative_to(dest_root)
            except ValueError as exc:
                raise ValueError(f"refusing to extract unsafe path from archive: {member.name}") from exc
        tf.extractall(dest_root)


def _remote_bundle_paths(run_id: str) -> tuple[str, str, str]:
    job_root = f"/tmp/hyops-runner-jobs/{run_id}"
    runtime_root = f"{job_root}/runtime"
    return job_root, runtime_root, f"{job_root}/runtime.bundle.tar.gz"


def _local_bundle_paths(paths, run_id: str) -> tuple[Path, Path]:
    stage_root = paths.work_dir / "runner" / run_id
    stage_root.mkdir(parents=True, exist_ok=True)
    return stage_root, stage_root / "runtime.bundle.tar.gz"


def _remote_result_archive(job_root: str) -> str:
    return f"{job_root}/runtime.result.tar.gz"


def _sync_runtime_to_runner(ctx: RunnerContext, *, paths, run_id: str, evidence_dir: Path) -> tuple[str, str]:
    _local_stage_root, local_bundle = _local_bundle_paths(paths, run_id)
    _bundle_runtime(paths, local_bundle)

    job_root, runtime_root, remote_bundle = _remote_bundle_paths(run_id)

    r = run_capture_stream(
        _ssh_argv(ctx, f"mkdir -p {shlex.quote(job_root)}"),
        evidence_dir=evidence_dir,
        label="runner_prepare",
        tee_path=evidence_dir / "runner.log",
        redact=True,
    )
    if r.rc != 0:
        raise RuntimeError("failed to create runner job directory")

    r = run_capture_stream(
        _scp_argv(ctx, str(local_bundle), remote_bundle, to_remote=True),
        evidence_dir=evidence_dir,
        label="runner_upload",
        tee_path=evidence_dir / "runner.log",
        redact=True,
    )
    if r.rc != 0:
        raise RuntimeError("failed to upload runner runtime bundle")

    remote_extract = (
        f"rm -rf {shlex.quote(runtime_root)} && "
        f"mkdir -p {shlex.quote(runtime_root)} && "
        f"tar -xzf {shlex.quote(remote_bundle)} -C {shlex.quote(runtime_root)}"
    )
    r = run_capture_stream(
        _ssh_argv(ctx, remote_extract),
        evidence_dir=evidence_dir,
        label="runner_extract",
        tee_path=evidence_dir / "runner.log",
        redact=True,
    )
    if r.rc != 0:
        raise RuntimeError("failed to extract runner runtime bundle")

    return job_root, runtime_root


def _sync_runtime_back(ctx: RunnerContext, *, paths, run_id: str, job_root: str, evidence_dir: Path) -> None:
    local_stage_root, _local_bundle = _local_bundle_paths(paths, run_id)
    local_result = local_stage_root / "runtime.result.tar.gz"
    remote_result = _remote_result_archive(job_root)
    runtime_root = f"{job_root}/runtime"
    list_script = " ; ".join(
        [
            "paths=()",
            *[
                f"[ -e {shlex.quote(name)} ] && paths+=({shlex.quote(name)})"
                for name in _RETURN_DIRS
            ],
            "if [ ${#paths[@]} -eq 0 ]; then exit 0; fi",
            f"tar -czf {shlex.quote(remote_result)} \"${{paths[@]}}\"",
        ]
    )
    r = run_capture_stream(
        _ssh_argv(ctx, f"bash -lc {shlex.quote(f'cd {shlex.quote(runtime_root)} && {list_script}') }"),
        evidence_dir=evidence_dir,
        label="runner_bundle_result",
        tee_path=evidence_dir / "runner.log",
        redact=True,
    )
    if r.rc != 0:
        raise RuntimeError("failed to bundle runner runtime result")
    if not remote_result:
        return

    r = run_capture_stream(
        _scp_argv(ctx, str(local_result), remote_result, to_remote=False),
        evidence_dir=evidence_dir,
        label="runner_download",
        tee_path=evidence_dir / "runner.log",
        redact=True,
    )
    if r.rc != 0:
        raise RuntimeError("failed to download runner runtime result")

    if local_result.exists():
        _safe_extract_archive(local_result, paths.root)


def _cleanup_remote_job(ctx: RunnerContext, *, job_root: str, evidence_dir: Path) -> None:
    run_capture_stream(
        _ssh_argv(ctx, f"rm -rf {shlex.quote(job_root)}"),
        evidence_dir=evidence_dir,
        label="runner_cleanup",
        tee_path=evidence_dir / "runner.log",
        redact=True,
    )


def _remote_blueprint_command(ns, *, runtime_root: str, remote_blueprint_path: str, ctx: RunnerContext) -> list[str]:
    cmd = [ctx.remote_hyops]
    if str(os.environ.get("HYOPS_VERBOSE") or "").strip().lower() in {"1", "true", "yes", "on"}:
        cmd.append("--verbose")
    cmd.extend(["blueprint", ns.runner_blueprint_cmd, "--root", runtime_root, "--file", remote_blueprint_path])
    if ns.runner_blueprint_cmd == "deploy":
        if bool(getattr(ns, "execute", False)):
            cmd.append("--execute")
        if bool(getattr(ns, "skip_preflight", False)):
            cmd.append("--skip-preflight")
        if bool(getattr(ns, "yes", False)):
            cmd.append("--yes")
    return cmd


def _resolve_sync_env_values(paths, keys: list[str]) -> tuple[dict[str, str], list[str], str]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    vault_issue = ""
    pending = [key for key in keys if key not in resolved]

    for key in pending:
        value = str(os.environ.get(key) or "").strip()
        if value:
            resolved[key] = value

    unresolved = [key for key in keys if key not in resolved]
    if unresolved:
        vault_file = (paths.root / "vault" / "bootstrap.vault.env").resolve()
        if vault_file.exists():
            try:
                vault_env = read_env(vault_file, VaultAuth())
            except Exception as exc:
                vault_env = {}
                vault_issue = str(exc).strip()
            for key in unresolved:
                value = str(vault_env.get(key) or "").strip()
                if value:
                    resolved[key] = value

    missing = [key for key in keys if key not in resolved]
    return resolved, missing, vault_issue


def _resolve_tfc_dispatch_env(paths) -> tuple[dict[str, str], dict[str, str]]:
    """
    Project Terraform Cloud credentials from the selected runtime into the
    runner-dispatched process when available.

    This keeps TFC as the Terraform backend while avoiding a second manual
    `hyops init terraform-cloud` step on every remote runner.
    """

    config_path = tfc_runtime_config_path(paths.root)
    if not config_path.exists():
        return {}, {"enabled": "false", "reason": "config_missing"}

    try:
        tfc = resolve_tfc_config(config_path=config_path)
    except Exception as exc:
        return {}, {"enabled": "false", "reason": f"config_error:{exc}"}

    host = str(tfc.host or "").strip()
    if not host:
        return {}, {"enabled": "false", "reason": "host_missing"}

    token_key = tf_token_env_key(host)
    token = str(os.environ.get(token_key) or "").strip()
    source = ""
    if token:
        source = "env"
    else:
        vault_file = (paths.root / "vault" / "bootstrap.vault.env").resolve()
        if vault_file.exists():
            try:
                vault_env = read_env(vault_file, VaultAuth())
            except Exception:
                vault_env = {}
            token = str(vault_env.get("TFC_TOKEN") or "").strip()
            if token:
                source = "runtime_vault"

    if not token:
        token = str(read_tfrc_token(tfc.credentials_file, host) or "").strip()
        if token:
            source = "credentials_file"

    if not token:
        return {}, {
            "enabled": "false",
            "reason": "token_missing",
            "host": host,
            "token_env_key": token_key,
            "credentials_file": str(tfc.credentials_file),
            "config_path": str(config_path),
        }

    return (
        {
            token_key: token,
            "TFC_HOST": host,
        },
        {
            "enabled": "true",
            "host": host,
            "token_env_key": token_key,
            "source": source,
            "credentials_file": str(tfc.credentials_file),
            "config_path": str(config_path),
        },
    )


def _resolve_gcp_dispatch_env(paths) -> tuple[dict[str, str], dict[str, str]]:
    """
    Project GCP ADC credentials from the local dispatcher into the remote runner
    job when available.

    Preferred order:
    1. explicit GOOGLE_CREDENTIALS env
    2. GOOGLE_APPLICATION_CREDENTIALS file contents
    3. runtime vault GOOGLE_CREDENTIALS
    4. local ADC file (~/.config/gcloud/application_default_credentials.json)
    """

    creds = str(os.environ.get("GOOGLE_CREDENTIALS") or "").strip()
    source = ""
    if creds:
        source = "env"
    else:
        adc_path = str(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
        if adc_path:
            candidate = Path(adc_path).expanduser().resolve()
            if candidate.exists() and candidate.is_file():
                try:
                    creds = candidate.read_text(encoding="utf-8").strip()
                except Exception:
                    creds = ""
                if creds:
                    source = "env_file"

    if not creds:
        vault_file = (paths.root / "vault" / "bootstrap.vault.env").resolve()
        if vault_file.exists():
            try:
                vault_env = read_env(vault_file, VaultAuth())
            except Exception:
                vault_env = {}
            creds = str(vault_env.get("GOOGLE_CREDENTIALS") or "").strip()
            if creds:
                source = "runtime_vault"

    if not creds:
        adc_candidate = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        if adc_candidate.exists() and adc_candidate.is_file():
            try:
                creds = adc_candidate.read_text(encoding="utf-8").strip()
            except Exception:
                creds = ""
            if creds:
                source = "adc_file"

    if not creds:
        return {}, {
            "enabled": "false",
            "reason": "credentials_missing",
            "adc_path": str((Path.home() / ".config" / "gcloud" / "application_default_credentials.json").resolve()),
        }

    return (
        {
            "GOOGLE_CREDENTIALS": creds,
        },
        {
            "enabled": "true",
            "source": source,
        },
    )


def _sync_secret_source_to_runtime(ns, *, paths) -> None:
    source = str(getattr(ns, "secret_source", "runtime") or "runtime").strip().lower() or "runtime"
    if source == "runtime":
        return
    if source == "gsm":
        rc, project_or_message = resolve_gsm_project_id(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            project_id_override=getattr(ns, "gsm_project_id", None),
            project_state_ref_override=getattr(ns, "gsm_project_state_ref", None),
        )
        if rc != 0:
            raise ValueError(project_or_message)
        project_id = project_or_message
        map_path = (
            Path(str(getattr(ns, "secret_map_file", "") or "")).expanduser().resolve()
            if str(getattr(ns, "secret_map_file", "") or "").strip()
            else resolve_default_gsm_map_file(str(os.environ.get("HYOPS_CORE_ROOT") or "").strip() or None)
        )
        if not map_path or not map_path.exists():
            raise ValueError(
                "GCP Secret Manager map file not found. Use --secret-map-file or set HYOPS_GSM_MAP_FILE."
            )
        auth = VaultAuth()
        rc, message = sync_gsm_to_runtime(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            scope=str(getattr(ns, "secret_scope", "all") or "all").strip() or "all",
            map_path=map_path,
            auth=auth,
            project_id=project_id,
            dry_run=False,
        )
        if rc != 0:
            raise ValueError(f"secret source sync failed: {message}")
        return
    if source != "vault":
        raise ValueError(f"unsupported secret source: {source}")

    vault_addr = str(getattr(ns, "vault_addr", None) or os.environ.get("VAULT_ADDR") or "").strip()
    if not vault_addr:
        raise ValueError("--vault-addr is required when --secret-source=vault (or set VAULT_ADDR)")
    token_env = str(getattr(ns, "vault_token_env", None) or "VAULT_TOKEN").strip() or "VAULT_TOKEN"
    token = str(os.environ.get(token_env) or "").strip()
    if not token:
        raise ValueError(
            f"environment variable {token_env} is required when --secret-source=vault"
        )

    map_path = (
        Path(str(getattr(ns, "secret_map_file", "") or "")).expanduser().resolve()
        if str(getattr(ns, "secret_map_file", "") or "").strip()
        else resolve_default_hashicorp_vault_map_file(str(os.environ.get("HYOPS_CORE_ROOT") or "").strip() or None)
    )
    if not map_path or not map_path.exists():
        raise ValueError(
            "Vault secret map file not found. Use --secret-map-file or set HYOPS_HASHICORP_VAULT_MAP_FILE."
        )

    auth = VaultAuth()
    rc, message = sync_hashicorp_vault_to_runtime(
        paths=paths,
        env_name=str(getattr(ns, "env", None) or paths.root.name),
        scope=str(getattr(ns, "secret_scope", "all") or "all").strip() or "all",
        map_path=map_path,
        auth=auth,
        vault_addr=vault_addr,
        token=token,
        namespace=str(getattr(ns, "vault_namespace", None) or os.environ.get("VAULT_NAMESPACE") or "").strip(),
        engine=str(getattr(ns, "vault_engine", "kv-v2") or "kv-v2").strip().lower() or "kv-v2",
        dry_run=False,
    )
    if rc != 0:
        raise ValueError(f"secret source sync failed: {message}")


def _execute_runner_blueprint(ns) -> int:
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops runner blueprint",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
        local_blueprints_root = (paths.config_dir / "blueprints").resolve()
        blueprint_path = _enforce_runtime_blueprint_file_scope(
            getattr(ns, "file", ""),
            allowed_root=local_blueprints_root,
        )
        _sync_secret_source_to_runtime(ns, paths=paths)
        ctx = _resolve_runner_context(
            paths,
            runner_state_ref=str(getattr(ns, "runner_state_ref", "") or ""),
            runner_vm_key=str(getattr(ns, "runner_vm_key", "") or ""),
        )
        sync_env_keys = [str(item or "").strip() for item in getattr(ns, "sync_env", []) if str(item or "").strip()]
        sync_env_values, missing_sync, vault_issue = _resolve_sync_env_values(paths, sync_env_keys)
        if missing_sync:
            if vault_issue:
                raise ValueError(
                    "runner dispatch could not read requested env vars from runtime vault "
                    f"({(paths.root / 'vault' / 'bootstrap.vault.env').resolve()}): {vault_issue}. "
                    "Unlock GPG in this shell with `hyops vault password >/dev/null`, "
                    "or provide the values via shell env for this one dispatch."
                )
            raise ValueError(
                "runner dispatch missing requested env vars in shell env or runtime vault: "
                + ", ".join(sorted(missing_sync))
            )
        tfc_env_values, tfc_meta = _resolve_tfc_dispatch_env(paths)
        gcp_env_values, gcp_meta = _resolve_gcp_dispatch_env(paths)
    except Exception as exc:
        print(f"ERR: runner blueprint setup failed: {exc}")
        return OPERATOR_ERROR

    run_id = new_run_id("runner")
    evidence_root = paths.logs_dir / "runner"
    evidence_dir = init_evidence_dir(evidence_root, run_id)
    ev = EvidenceWriter(evidence_dir)
    ev.write_json(
        "dispatch.request.json",
        {
            "runner_state_ref": ctx.state_ref,
            "runner_vm_key": ctx.vm_key,
            "runtime_root": str(paths.root),
            "blueprint_file": str(blueprint_path),
            "runner_blueprint_cmd": ns.runner_blueprint_cmd,
            "sync_env": sync_env_keys,
            "tfc_dispatch": tfc_meta,
            "gcp_dispatch": gcp_meta,
        },
    )
    print(f"runner={ctx.state_ref} status=running run_id={run_id}")
    print(f"evidence: {evidence_dir}")

    job_root = ""
    try:
        job_root, runtime_root = _sync_runtime_to_runner(ctx, paths=paths, run_id=run_id, evidence_dir=evidence_dir)
        remote_blueprint_path = f"{runtime_root}/config/blueprints/{blueprint_path.name}"
        remote_cmd = _remote_blueprint_command(
            ns,
            runtime_root=runtime_root,
            remote_blueprint_path=remote_blueprint_path,
            ctx=ctx,
        )
        env_prefix = [f"HYOPS_CORE_ROOT={shlex.quote(ctx.remote_core_root)}"]
        env_prefix.extend(f"{key}={shlex.quote(value)}" for key, value in sorted(tfc_env_values.items()))
        env_prefix.extend(f"{key}={shlex.quote(value)}" for key, value in sorted(gcp_env_values.items()))
        env_prefix.extend(f"{key}={shlex.quote(sync_env_values[key])}" for key in sync_env_keys)
        remote_shell = " ".join(env_prefix) + " " + " ".join(
            shlex.quote(part) for part in remote_cmd
        )
        remote_run = run_capture_stream(
            _ssh_argv(ctx, f"bash -lc {shlex.quote(remote_shell)}"),
            evidence_dir=evidence_dir,
            label="runner_exec",
            tee_path=evidence_dir / "runner.log",
            redact=True,
        )
        _sync_runtime_back(ctx, paths=paths, run_id=run_id, job_root=job_root, evidence_dir=evidence_dir)
        if remote_run.rc != 0:
            print(f"runner={ctx.state_ref} status=error run_id={run_id}")
            print(f"evidence: {evidence_dir}")
            remote_stdout = str(getattr(remote_run, "stdout", "") or "")
            if "Terraform Cloud backend selected but no Terraform Cloud token was found" in remote_stdout:
                env_name = str(getattr(ns, "env", "") or "").strip()
                hint_env = f" --env {env_name}" if env_name else ""
                print(
                    "hint: runner-executed Terraform/Terragrunt steps need local Terraform Cloud init "
                    "so dispatch can project TFC auth to the runner. "
                    f"Run: hyops init terraform-cloud{hint_env} --with-cli-login"
                )
            if 'metadata "instance/service-accounts/default/token' in remote_stdout:
                env_name = str(getattr(ns, "env", "") or "").strip()
                hint_env = f" --env {env_name}" if env_name else ""
                print(
                    "hint: runner-executed GCP Terraform steps need dispatcher-side ADC or explicit GOOGLE_CREDENTIALS "
                    "so dispatch can project GCP auth to the runner. "
                    f"Run: hyops init gcp{hint_env} --with-cli-login"
                )
            print("error: runner remote hyops command failed (open runner_exec.stdout.txt / runner_exec.stderr.txt)")
            return OPERATOR_ERROR
    except Exception as exc:
        print(f"runner={ctx.state_ref} status=error run_id={run_id}")
        print(f"evidence: {evidence_dir}")
        print(f"error: runner dispatch failed: {exc}")
        return OPERATOR_ERROR
    finally:
        if job_root and not bool(getattr(ns, "keep_remote_job", False)):
            _cleanup_remote_job(ctx, job_root=job_root, evidence_dir=evidence_dir)

    ev.write_json(
        "dispatch.result.json",
        {
            "runner_state_ref": ctx.state_ref,
            "runner_vm_key": ctx.vm_key,
            "status": "ok",
            "run_id": run_id,
        },
    )
    print(f"runner={ctx.state_ref} status=ok run_id={run_id}")
    print(f"evidence: {evidence_dir}")
    return 0


def run_runner_blueprint_preflight(ns) -> int:
    return _execute_runner_blueprint(ns)


def run_runner_blueprint_deploy(ns) -> int:
    return _execute_runner_blueprint(ns)
