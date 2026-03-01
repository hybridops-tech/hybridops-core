# hyops/vault/command.py
# purpose: Vault helper command family (password provider + bootstrap/status/reset).
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Studio

from __future__ import annotations

import argparse
import os
import subprocess
import shlex
import stat
import sys
from pathlib import Path

from hyops.runtime.exitcodes import INTERNAL_ERROR


def add_vault_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("vault", help="Vault password provider helpers.")
    p.add_argument(
        "--script",
        default=None,
        help="Override provider script path (default: tools/secrets/vault/vault-pass.sh).",
    )
    ssp = p.add_subparsers(dest="vault_cmd", required=True)

    _add(ssp, "status", "Exit 0 if ready, else 1.")
    _add(ssp, "status-verbose", "Print ready|not ready and exit 0|1.")
    _add(ssp, "bootstrap", "Interactive bootstrap (stores password in pass).")
    _add(ssp, "reset", "Remove stored entry.")
    _add(ssp, "password", "Emit vault password for automation (hidden on interactive terminals).")

    p.set_defaults(_handler=_dispatch)


def _add(sp: argparse._SubParsersAction, name: str, help_text: str):
    q = sp.add_parser(name, help=help_text)
    q.set_defaults(_vault_action=name)
    return q


def _find_core_root() -> Path | None:
    # 1) explicit env
    env_root = os.environ.get("HYOPS_CORE_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    # 2) walk up from CWD (supports extracted tarball use)
    cur = Path.cwd().resolve()
    for _ in range(0, 6):
        candidate = cur / "tools" / "secrets" / "vault" / "vault-pass.sh"
        if candidate.exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent

    # 3) best-effort git root
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip()).resolve()
    except Exception:
        pass

    return None


def _default_password_command_file() -> Path:
    return (Path.home() / ".hybridops" / "config" / "vault-password-command").resolve()


def _default_script() -> Path | None:
    env_script = os.environ.get("HYOPS_VAULT_PASS_SCRIPT", "").strip()
    if env_script:
        return Path(env_script).expanduser().resolve()

    root = _find_core_root()
    if not root:
        return None
    return root / "tools" / "secrets" / "vault" / "vault-pass.sh"


def _dispatch(ns) -> int:
    script = Path(ns.script).expanduser().resolve() if ns.script else _default_script()
    if not script or not script.exists():
        print("ERR: vault provider script not found. Set HYOPS_CORE_ROOT/HYOPS_VAULT_PASS_SCRIPT or pass --script.")
        return INTERNAL_ERROR

    action = ns._vault_action

    args = [str(script)]
    if action == "status":
        args += ["--status"]
    elif action == "status-verbose":
        args += ["--status-verbose"]
    elif action == "bootstrap":
        args += ["--bootstrap"]
    elif action == "reset":
        args += ["--reset"]
    elif action == "password":
        # IMPORTANT: must print only the password to stdout; the script already does that.
        pass
    else:
        print(f"ERR: unknown vault action: {action}")
        return INTERNAL_ERROR

    timeout_s: int | None = None
    if action in ("status", "status-verbose", "password"):
        raw_timeout = str(os.environ.get("HYOPS_VAULT_HELPER_TIMEOUT_S") or "25").strip()
        try:
            parsed = int(raw_timeout)
            timeout_s = parsed if parsed >= 5 else 25
        except Exception:
            timeout_s = 25

    try:
        hide_interactive_password = bool(action == "password" and sys.stdout.isatty())
        if hide_interactive_password:
            completed = subprocess.run(
                args,
                check=False,
                timeout=timeout_s,
                capture_output=True,
                text=True,
            )
        else:
            completed = subprocess.run(args, check=False, timeout=timeout_s)
        rc = int(completed.returncode)
    except subprocess.TimeoutExpired:
        print(
            f"ERR: vault helper timed out after {timeout_s}s while running action={action}; "
            "verify GPG/pinentry is usable in this shell.",
            file=sys.stderr,
        )
        return INTERNAL_ERROR
    except KeyboardInterrupt:
        print("Cancelled.")
        return 2

    if hide_interactive_password and rc == 0:
        print(
            "[hyops] vault password retrieved (hidden). "
            "Password is emitted only for non-interactive stdout (for example pipe/redirection).",
            file=sys.stderr,
        )
    elif hide_interactive_password and rc != 0:
        stderr_text = (getattr(completed, "stderr", None) or "").strip()
        stdout_text = (getattr(completed, "stdout", None) or "").strip()
        if stderr_text:
            print(stderr_text, file=sys.stderr)
        elif stdout_text:
            print(stdout_text, file=sys.stderr)

    # Persist provider command for other hyops commands (workstation-level, not per-env).
    if action == "bootstrap" and rc == 0:
        try:
            cfg = _default_password_command_file()
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(shlex.quote(str(script)) + "\n", encoding="utf-8")
            os.chmod(cfg, stat.S_IRUSR | stat.S_IWUSR)
            print(f"[hyops] configured default vault password command: {cfg}", file=sys.stderr)
        except Exception:
            # Best-effort: do not fail bootstrap if config persistence fails.
            pass

    return rc
