"""Setup command.

purpose: Run explicit prerequisite installers (system and runtime deps).
Architecture Decision: ADR-N/A (setup)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from hyops.runtime.exitcodes import OK, INTERNAL_ERROR, OPERATOR_ERROR
from hyops.runtime.paths import resolve_runtime_paths


def add_setup_subparser(sp: argparse._SubParsersAction) -> None:
    # Common args must be present on both the setup parser and subcommands so operators can run:
    #   hyops setup base --sudo
    #   hyops setup ansible
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        "--core-root",
        default=None,
        help="Core root containing tools/setup (default: HYOPS_CORE_ROOT or cwd discovery).",
    )
    common.add_argument(
        "--env",
        default=None,
        help="Target runtime environment for installers that write into runtime state (e.g. ansible).",
    )
    common.add_argument(
        "--runtime-root",
        default=None,
        help="Override runtime root for installers that write into runtime state (mutually exclusive with --env).",
    )
    common.add_argument(
        "--sudo",
        action="store_true",
        help="Run setup script via sudo (recommended for system installers).",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved script path and exit.",
    )

    common.add_argument(
        "--force",
        action="store_true",
        help="Force reinstall where supported (currently: ansible, all).",
    )

    p = sp.add_parser("setup", help="Install prerequisites (explicit operator action).", parents=[common])
    ssp = p.add_subparsers(dest="setup_cmd", required=True)

    _add(ssp, "base", "Install base system prerequisites.", parents=[common])
    _add(ssp, "ansible", "Install Ansible Galaxy dependencies into the runtime state directory.", parents=[common])
    _add(ssp, "cloud-azure", "Install Azure CLI prerequisites.", parents=[common])
    _add(ssp, "cloud-gcp", "Install GCP SDK prerequisites.", parents=[common])
    _add(ssp, "all", "Run base + ansible + cloud installers.", parents=[common])
    _add(ssp, "check", "Check presence of common tools (no installs).", parents=[common])

    # Aliases (operator-friendly)
    _add(ssp, "config-mgmt", "Alias for: ansible.", parents=[common])
    _add(ssp, "config-management", "Alias for: ansible.", parents=[common])

    p.set_defaults(_handler=run)


def _add(
    sp: argparse._SubParsersAction,
    name: str,
    help_text: str,
    *,
    parents: list[argparse.ArgumentParser] | None = None,
) -> None:
    q = sp.add_parser(name, help=help_text, parents=parents or [])
    q.set_defaults(_setup_action=name)


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
    if action in ("config-mgmt", "config-management"):
        action = "ansible"

    mapping = {
        "base": "setup-base.sh",
        "ansible": "setup-ansible.sh",
        "cloud-azure": "setup-cloud-azure.sh",
        "cloud-gcp": "setup-cloud-gcp.sh",
        "all": "setup-all.sh",
    }
    return mapping.get(action)


def _run_check() -> int:
    checks: list[tuple[str, list[str]]] = [
        ("python3", ["python3"]),
        ("ssh", ["ssh"]),
        ("scp", ["scp"]),
        ("ansible-vault", ["ansible-vault"]),
        ("ansible-galaxy", ["ansible-galaxy"]),
        ("terraform", ["terraform"]),
        ("packer", ["packer"]),
        ("kubectl", ["kubectl"]),
        ("gh", ["gh"]),
        ("az", ["az"]),
        ("gcloud", ["gcloud"]),
        ("gpg", ["gpg"]),
        ("pass", ["pass"]),
        # Different distros provide different pinentry flavors.
        ("pinentry", ["pinentry", "pinentry-curses", "pinentry-tty", "pinentry-gtk-2"]),
    ]
    ok = True
    for label, candidates in checks:
        found = ""
        for cand in candidates:
            rc = subprocess.call(["/usr/bin/env", "bash", "-lc", f"command -v {cand} >/dev/null 2>&1"])
            if rc == 0:
                found = cand
                break
        if found:
            suffix = f" ({found})" if found != label else ""
            print(f"installed {label}{suffix}")
        else:
            print(f"missing   {label}")
            ok = False
    return OK if ok else 2


def run(ns) -> int:
    action = ns._setup_action

    if action == "check":
        return _run_check()

    canonical_action = "ansible" if action in ("config-mgmt", "config-management") else action

    runtime_root: Path | None = None
    if canonical_action in ("ansible", "all"):
        if ns.runtime_root and ns.env:
            print("ERR: --runtime-root and --env are mutually exclusive")
            return OPERATOR_ERROR

        try:
            runtime_root = resolve_runtime_paths(root=ns.runtime_root, env=ns.env).root
        except ValueError as exc:
            print(f"ERR: {exc}")
            return OPERATOR_ERROR

    if canonical_action == "ansible" and ns.sudo:
        print("ERR: hyops setup ansible must not be run with --sudo (it installs into user runtime state)")
        return OPERATOR_ERROR

    script_name = _script_for(canonical_action)
    if not script_name:
        print(f"ERR: unsupported setup action: {canonical_action}")
        return INTERNAL_ERROR

    core_root = _find_core_root(ns.root)
    if not core_root:
        print("ERR: tools/setup not found. Set HYOPS_CORE_ROOT or pass: hyops setup --root <path> ...")
        return INTERNAL_ERROR

    script = (core_root / "tools" / "setup" / script_name).resolve()
    if not script.exists():
        print(f"ERR: setup script not found: {script}")
        return INTERNAL_ERROR

    if ns.dry_run:
        print(str(script))
        if runtime_root is not None:
            print(f"runtime_root={runtime_root}")
        return OK

    env = os.environ.copy()
    if runtime_root is not None:
        env["HYOPS_RUNTIME_ROOT"] = str(runtime_root)
        if (ns.env or "").strip():
            env["HYOPS_ENV"] = str(ns.env).strip()

    argv: list[str] = ["bash", str(script)]
    if canonical_action == "ansible" and runtime_root is not None:
        argv += ["--root", str(runtime_root)]
    if ns.force and canonical_action in ("ansible", "all"):
        argv += ["--force"]
    if ns.sudo:
        argv = ["sudo", "-E"] + argv
    rc = subprocess.call(argv, env=env)
    return int(rc)
