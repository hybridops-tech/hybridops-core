"""Setup command.

purpose: Run explicit prerequisite installers (system and runtime deps).
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from hyops.runtime.exitcodes import CANCELLED, OK, INTERNAL_ERROR, OPERATOR_ERROR
from hyops.runtime.command_evidence import PythonCommandEvidence, command_evidence_dir, run_streamed
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.progress import ProgressDisplay, verbose_enabled


TARGET_STEPS = {
    "gcp": ("base", "cloud-gcp", "galaxy"),
    "azure": ("base", "cloud-azure", "galaxy"),
    "proxmox": ("base", "galaxy"),
    "all": ("base", "cloud-azure", "cloud-gcp", "galaxy"),
}

SETUP_LABELS = {
    "base": "Base tools",
    "cloud-gcp": "GCP tools",
    "cloud-azure": "Azure tools",
    "galaxy": "Galaxy dependencies",
    "all": "All setup components",
}

SETUP_PHASE_COUNTS = {
    "base": 7,
    "cloud-gcp": 3,
    "cloud-azure": 3,
    "galaxy": 8,
}

TARGET_LABELS = {
    "gcp": "GCP",
    "azure": "Azure",
    "proxmox": "Proxmox",
    "all": "All components",
}

READINESS_TARGETS = ("all", "base", "gcp", "azure", "proxmox")
READINESS_GROUPS = {
    "base-runtime": (
        ("python3", ("python3",)),
        ("ssh", ("ssh",)),
        ("scp", ("scp",)),
        ("ansible-vault", ("ansible-vault",)),
        ("ansible-galaxy", ("ansible-galaxy",)),
        ("terraform", ("terraform",)),
        ("terragrunt", ("terragrunt",)),
        ("packer", ("packer",)),
        ("kubectl", ("kubectl",)),
    ),
    "vault-support": (
        ("gpg", ("gpg",)),
        ("pass", ("pass",)),
        (
            "pinentry",
            (
                "pinentry",
                "pinentry-mac",
                "pinentry-curses",
                "pinentry-tty",
                "pinentry-gtk-2",
            ),
        ),
    ),
    "gcp-support": (
        ("gcloud", ("gcloud",)),
        ("gke-gcloud-auth-plugin", ("gke-gcloud-auth-plugin",)),
    ),
    "azure-support": (("az", ("az",)),),
}
READINESS_GROUPS_BY_TARGET = {
    "base": ("base-runtime", "vault-support"),
    "gcp": ("base-runtime", "vault-support", "gcp-support", "galaxy-dependencies"),
    "azure": ("base-runtime", "vault-support", "azure-support", "galaxy-dependencies"),
    "proxmox": ("base-runtime", "vault-support", "galaxy-dependencies"),
    "all": (
        "base-runtime",
        "vault-support",
        "gcp-support",
        "azure-support",
        "galaxy-dependencies",
    ),
}
PROGRESS_PREFIX = "[hyops-progress] "


def _setup_phase_count(step: str) -> int:
    if step == "base" and os.uname().sysname == "Darwin":
        return 5
    return SETUP_PHASE_COUNTS.get(step, 1)


def _update_setup_progress(
    progress: ProgressDisplay,
    step: str,
    base_label: str,
    line: str,
    *,
    completed_phases: int = 0,
    total_phases: int = 1,
    phase_positions: dict[str, int] | None = None,
) -> None:
    if line.startswith(PROGRESS_PREFIX):
        phase = line[len(PROGRESS_PREFIX) :].strip()
        if phase:
            position = 1
            if phase_positions is not None:
                position = phase_positions.get(step, 0) + 1
                phase_positions[step] = position
            started = completed_phases + max(0.5, position - 0.5)
            percent = min(99, int((started * 100) / max(1, total_phases)))
            label = f"{base_label}: {phase}"
            progress.update(step, f"{label}  {percent}%")
            next_boundary = min(
                99,
                max(
                    percent,
                    int(
                        (completed_phases + max(1, position))
                        * 100
                        / max(1, total_phases)
                    )
                    - 1,
                ),
            )
            progress.track_percent(
                step,
                label,
                current=percent,
                ceiling=next_boundary,
            )


def add_setup_subparser(sp: argparse._SubParsersAction) -> None:
    # Common args must be present on both the setup parser and subcommands so operators can run:
    #   hyops setup base --sudo
    #   hyops setup galaxy
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Stream setup output while retaining the run record.",
    )
    common.add_argument(
        "--root",
        "--core-root",
        dest="root",
        default=argparse.SUPPRESS,
        help="Core root containing tools/setup (default: HYOPS_CORE_ROOT or cwd discovery).",
    )
    common.add_argument(
        "--env",
        default=argparse.SUPPRESS,
        help=(
            "Target runtime environment for installers that write into runtime state "
            "(for example, Galaxy)."
        ),
    )
    common.add_argument(
        "--runtime-root",
        default=argparse.SUPPRESS,
        help=(
            "Override runtime root for installers that write into runtime state "
            "(mutually exclusive with --env)."
        ),
    )
    common.add_argument(
        "--sudo",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Run an individual setup script via sudo; target setup elevates "
            "system stages automatically."
        ),
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print the resolved script path and exit.",
    )

    common.add_argument(
        "--force",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Force Galaxy dependency installation where supported.",
    )
    common.add_argument(
        "--hybridops-source",
        choices=("release", "git"),
        default=argparse.SUPPRESS,
        help=(
            "How to source HybridOps collections for setup galaxy/all or target setup. "
            "release installs the pinned published collection artifacts; git installs pinned "
            "collections from Git repositories into runtime state."
        ),
    )
    common.add_argument(
        "--hybridops-git-manifest",
        default=argparse.SUPPRESS,
        help=(
            "Override the HybridOps Git collection manifest used with --hybridops-source git. "
            "Useful for local iteration against a custom pinned manifest."
        ),
    )

    p = sp.add_parser(
        "setup",
        help="Install prerequisites (explicit operator action).",
        parents=[common],
    )
    ssp = p.add_subparsers(dest="setup_cmd", required=True)

    _add(ssp, "base", "Install base system prerequisites.", parents=[common])
    _add(
        ssp,
        "galaxy",
        "Install Ansible Galaxy dependencies into runtime state.",
        parents=[common],
    )
    _add(ssp, "cloud-azure", "Install Azure CLI prerequisites.", parents=[common])
    _add(ssp, "cloud-gcp", "Install GCP SDK prerequisites.", parents=[common])
    _add(ssp, "all", "Run base + ansible + cloud installers.", parents=[common])
    check = _add(
        ssp,
        "check",
        "Check readiness for one setup target (no installs).",
        parents=[common],
    )
    check.add_argument(
        "target",
        nargs="?",
        choices=READINESS_TARGETS,
        default="all",
        help="Readiness target (default: all).",
    )

    # Compatibility aliases and complete target setup commands.
    _add(ssp, "ansible", "Compatibility alias for: galaxy.", parents=[common])
    _add(ssp, "config-mgmt", "Alias for: galaxy.", parents=[common])
    _add(ssp, "config-management", "Alias for: galaxy.", parents=[common])
    _add(ssp, "azure", "Install Azure workstation prerequisites.", parents=[common])
    _add(ssp, "gcp", "Install GCP workstation prerequisites.", parents=[common])
    _add(ssp, "proxmox", "Install Proxmox workstation prerequisites.", parents=[common])

    p.set_defaults(_handler=run)


def _add(
    sp: argparse._SubParsersAction,
    name: str,
    help_text: str,
    *,
    parents: list[argparse.ArgumentParser] | None = None,
) -> argparse.ArgumentParser:
    q = sp.add_parser(name, help=help_text, parents=parents or [])
    q.set_defaults(_setup_action=name)
    return q


def _find_core_root(ns_root: str | None) -> Path | None:
    if ns_root:
        return Path(ns_root).expanduser().resolve()

    env_root = os.environ.get("HYOPS_CORE_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    cur = Path.cwd().resolve()
    for _ in range(0, 8):
        candidate = cur / "tools" / "setup"
        if candidate.exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent

    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
        if r.returncode == 0:
            root = Path(r.stdout.strip()).resolve()
            if (root / "tools" / "setup").exists():
                return root
    except Exception:
        pass

    return None


def _script_for(action: str) -> str | None:
    if action in ("ansible", "config-mgmt", "config-management"):
        action = "galaxy"
    elif action == "azure":
        action = "cloud-azure"
    elif action == "gcp":
        action = "cloud-gcp"

    mapping = {
        "base": "setup-base.sh",
        "galaxy": "setup-ansible.sh",
        "cloud-azure": "setup-cloud-azure.sh",
        "cloud-gcp": "setup-cloud-gcp.sh",
        "all": "setup-all.sh",
    }
    return mapping.get(action)


def _setup_argv(
    action: str,
    script: Path,
    *,
    runtime_root: Path | None,
    force: bool,
    hybridops_source: str | None,
    hybridops_git_manifest: str | None,
    elevate: bool,
) -> list[str]:
    argv = ["bash", str(script)]
    if action == "galaxy" and runtime_root is not None:
        argv += ["--root", str(runtime_root)]
    if force and action in ("galaxy", "all"):
        argv += ["--force"]
    if hybridops_source and action in ("galaxy", "all"):
        argv += ["--hybridops-source", hybridops_source]
    if hybridops_git_manifest and action in ("galaxy", "all"):
        argv += ["--hybridops-git-manifest", hybridops_git_manifest]
    if elevate:
        argv = ["sudo", "-H", "-E"] + argv
    return argv


def _missing_commands(
    checks: tuple[tuple[str, tuple[str, ...]], ...],
) -> list[str]:
    missing: list[str] = []
    for label, candidates in checks:
        if not any(shutil.which(candidate) for candidate in candidates):
            missing.append(label)
    return missing


def _galaxy_readiness(runtime_root: Path) -> list[str]:
    marker = runtime_root / "state" / "ansible" / ".installed.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        collections_dir = Path(str(payload["collections_dir"])).expanduser()
    except (OSError, ValueError, KeyError, TypeError):
        return ["run: hyops setup galaxy"]
    if not collections_dir.is_dir():
        return ["run: hyops setup galaxy"]
    return []


def _run_check(target: str, runtime_root: Path) -> int:
    print(f"setup target: {target}")
    ready = True
    for group in READINESS_GROUPS_BY_TARGET[target]:
        if group == "galaxy-dependencies":
            missing = _galaxy_readiness(runtime_root)
        else:
            missing = _missing_commands(READINESS_GROUPS[group])

        if missing:
            print(f"missing {group}: {', '.join(missing)}")
            ready = False
        else:
            print(f"ok      {group}")

    print(f"status={'ready' if ready else 'not-ready'}")
    return OK if ready else OPERATOR_ERROR


def run(ns) -> int:
    action = ns._setup_action
    aliases = {
        "ansible": "galaxy",
        "config-mgmt": "galaxy",
        "config-management": "galaxy",
    }
    canonical_action = aliases.get(action, action)

    runtime_root: Path | None = None
    runtime_root_arg = getattr(ns, "runtime_root", None)
    env_arg = getattr(ns, "env", None)
    sudo = bool(getattr(ns, "sudo", False))
    dry_run = bool(getattr(ns, "dry_run", False))
    force = bool(getattr(ns, "force", False))
    hybridops_source = getattr(ns, "hybridops_source", None)
    hybridops_git_manifest = getattr(ns, "hybridops_git_manifest", None)

    if action == "check":
        evidence_paths = resolve_runtime_paths(root=runtime_root_arg, env=env_arg)
        ensure_layout(evidence_paths)
        evidence_dir = command_evidence_dir(evidence_paths.logs_dir, "setup", canonical_action)
        with PythonCommandEvidence(
            evidence_dir,
            command="setup check",
            argv=sys.argv[1:],
        ) as evidence:
            evidence.exit_code = _run_check(ns.target, evidence_paths.root)
            return evidence.exit_code

    if canonical_action in ("galaxy", "all", *TARGET_STEPS):
        if runtime_root_arg and env_arg:
            print("ERR: --runtime-root and --env are mutually exclusive")
            return OPERATOR_ERROR

        try:
            runtime_root = resolve_runtime_paths(root=runtime_root_arg, env=env_arg).root
        except ValueError as exc:
            print(f"ERR: {exc}")
            return OPERATOR_ERROR

    if canonical_action == "galaxy" and sudo:
        print(
            "ERR: hyops setup galaxy must not use --sudo "
            "(it writes to user runtime state)"
        )
        return OPERATOR_ERROR

    script_name = _script_for(canonical_action)
    if not script_name and canonical_action not in TARGET_STEPS:
        print(f"ERR: unsupported setup action: {canonical_action}")
        return INTERNAL_ERROR

    core_root = _find_core_root(getattr(ns, "root", None))
    if not core_root:
        print(
            "ERR: tools/setup not found. Set HYOPS_CORE_ROOT or pass: "
            "hyops setup --root <path> ..."
        )
        return INTERNAL_ERROR

    if canonical_action in TARGET_STEPS:
        steps = TARGET_STEPS[canonical_action]
        if dry_run:
            print(f"setup={canonical_action}")
            for step in steps:
                path = (core_root / "tools" / "setup" / str(_script_for(step))).resolve()
                print(f"- {step}: {path}")
            if runtime_root is not None:
                print(f"runtime_root={runtime_root}")
            return OK

        env = os.environ.copy()
        if runtime_root is not None:
            env["HYOPS_RUNTIME_ROOT"] = str(runtime_root)
            if (env_arg or "").strip():
                env["HYOPS_ENV"] = str(env_arg).strip()

        evidence_paths = resolve_runtime_paths(root=runtime_root_arg, env=env_arg)
        ensure_layout(evidence_paths)
        progress = ProgressDisplay(show_elapsed=False)
        print(f"Setup target: {TARGET_LABELS[canonical_action]}")
        total_phases = sum(_setup_phase_count(step) for step in steps)
        completed_phases = 0
        phase_positions: dict[str, int] = {}
        requires_sudo = os.uname().sysname != "Darwin" and any(
            step != "galaxy" for step in steps
        )
        if requires_sudo and sys.stdin.isatty() and sys.stdout.isatty():
            print("Administrator access is required for system setup.")
            if subprocess.call(["sudo", "-v"]) != 0:
                print("ERR: administrator authentication failed")
                return OPERATOR_ERROR
        for step_index, step in enumerate(steps, start=1):
            step_script = (
                core_root / "tools" / "setup" / str(_script_for(step))
            ).resolve()
            if not step_script.exists():
                print(f"ERR: setup script not found: {step_script}")
                return INTERNAL_ERROR
            argv = _setup_argv(
                step,
                step_script,
                runtime_root=runtime_root,
                force=force,
                hybridops_source=hybridops_source,
                hybridops_git_manifest=hybridops_git_manifest,
                elevate=step != "galaxy" and os.uname().sysname != "Darwin",
            )
            label = SETUP_LABELS[step]
            running_percent = (completed_phases * 100) // max(1, total_phases)
            running_label = f"{label}  {step_index}/{len(steps)}  {running_percent}%"
            evidence_dir = command_evidence_dir(
                evidence_paths.logs_dir,
                "setup",
                f"{canonical_action}/{step}",
            )
            progress.start(
                step,
                running_label,
                plain=(
                    f"setup={canonical_action} stage={step} status=running "
                    f"progress={running_percent}%"
                ),
            )
            rc = run_streamed(
                argv,
                env=env,
                evidence_dir=evidence_dir,
                command=f"setup {canonical_action} {step}",
                stream_output=verbose_enabled(),
                announce=False,
                line_callback=lambda line, step=step, label=label, completed_phases=completed_phases: _update_setup_progress(
                    progress,
                    step,
                    label,
                    line,
                    completed_phases=completed_phases,
                    total_phases=total_phases,
                    phase_positions=phase_positions,
                ),
            )
            if rc != 0:
                confirmed = completed_phases + max(0, phase_positions.get(step, 1) - 1)
                failed_percent = min(99, (confirmed * 100) // max(1, total_phases))
                progress.finish(
                    step,
                    f"{label}  {step_index}/{len(steps)}  {failed_percent}%",
                    "cancelled" if rc == CANCELLED else "failed",
                    plain=(
                        f"setup={canonical_action} stage={step} "
                        f"status={'cancelled' if rc == CANCELLED else 'failed'} "
                        f"progress={failed_percent}%"
                    ),
                )
                print(f"run record: {evidence_dir}")
                print(f"rerun: hyops setup {canonical_action} --verbose")
                return rc
            completed_phases += _setup_phase_count(step)
            completed_percent = (completed_phases * 100) // max(1, total_phases)
            progress.finish(
                step,
                f"{label}  {step_index}/{len(steps)}  {completed_percent}%",
                "ok",
                plain=(
                    f"setup={canonical_action} stage={step} status=ok "
                    f"progress={completed_percent}%"
                ),
            )
        print(f"setup={canonical_action} status=ok")
        print(f"run records: {evidence_paths.logs_dir / 'setup' / canonical_action}")
        return OK

    script = (core_root / "tools" / "setup" / script_name).resolve()
    if not script.exists():
        print(f"ERR: setup script not found: {script}")
        return INTERNAL_ERROR

    if dry_run:
        print(str(script))
        if runtime_root is not None:
            print(f"runtime_root={runtime_root}")
        return OK

    env = os.environ.copy()
    if runtime_root is not None:
        env["HYOPS_RUNTIME_ROOT"] = str(runtime_root)
        if (env_arg or "").strip():
            env["HYOPS_ENV"] = str(env_arg).strip()

    auto_elevate = (
        os.uname().sysname != "Darwin"
        and canonical_action in ("base", "cloud-gcp", "cloud-azure", "all")
    )
    elevate = sudo or auto_elevate
    if (
        elevate
        and os.uname().sysname != "Darwin"
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        print("Administrator access is required for system setup.")
        if subprocess.call(["sudo", "-v"]) != 0:
            print("ERR: administrator authentication failed")
            return OPERATOR_ERROR

    argv = _setup_argv(
        canonical_action,
        script,
        runtime_root=runtime_root,
        force=force,
        hybridops_source=hybridops_source,
        hybridops_git_manifest=hybridops_git_manifest,
        elevate=elevate,
    )
    evidence_paths = resolve_runtime_paths(root=runtime_root_arg, env=env_arg)
    ensure_layout(evidence_paths)
    evidence_dir = command_evidence_dir(evidence_paths.logs_dir, "setup", canonical_action)
    label = SETUP_LABELS.get(canonical_action, canonical_action)
    stream_verbose = verbose_enabled()
    progress = ProgressDisplay(show_elapsed=False)
    total_phases = _setup_phase_count(canonical_action)
    phase_positions: dict[str, int] = {}
    progress.start(
        canonical_action,
        f"{label}  0%",
        plain=(
            f"setup={canonical_action} status=running"
            if stream_verbose
            else f"setup={canonical_action} status=running progress=0%"
        ),
    )
    rc = run_streamed(
        argv,
        env=env,
        evidence_dir=evidence_dir,
        command=f"setup {canonical_action}",
        stream_output=stream_verbose,
        announce=False,
        line_callback=lambda line: _update_setup_progress(
            progress,
            canonical_action,
            label,
            line,
            total_phases=total_phases,
            phase_positions=phase_positions,
        ),
    )
    if rc == 0:
        progress.finish(
            canonical_action,
            f"{label}  100%",
            "ok",
            plain=(
                f"setup={canonical_action} status=ok"
                if stream_verbose
                else f"setup={canonical_action} status=ok progress=100%"
            ),
        )
    else:
        completed = max(0, phase_positions.get(canonical_action, 1) - 1)
        failed_percent = min(99, (completed * 100) // max(1, total_phases))
        progress.finish(
            canonical_action,
            f"{label}  {failed_percent}%",
            "cancelled" if rc == CANCELLED else "failed",
            plain=(
                (
                    f"setup={canonical_action} "
                    f"status={'cancelled' if rc == CANCELLED else 'failed'}"
                )
                if stream_verbose
                else (
                    f"setup={canonical_action} "
                    f"status={'cancelled' if rc == CANCELLED else 'failed'} "
                    f"progress={failed_percent}%"
                )
            ),
        )
    print(f"run record: {evidence_dir}")
    if rc != 0:
        print(f"rerun: hyops setup {action} --verbose")
    return rc
