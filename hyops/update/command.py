"""
purpose: Expose explicit Core release checks through the HybridOps CLI.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json

from hyops.runtime.exitcodes import OK
from hyops.update.checker import UpdateStatus, check_for_update


def add_update_subparser(sp: argparse._SubParsersAction) -> None:
    parser = sp.add_parser("update", help="Check Core release status.")
    commands = parser.add_subparsers(dest="update_cmd", required=True)
    check = commands.add_parser("check", help="Compare the installed and current releases.")
    check.add_argument("--no-cache", action="store_true", help="Query the release service now.")
    check.add_argument("--json", action="store_true", help="Print machine-readable output.")
    check.add_argument("--root", help="Runtime root used for the update-check cache.")
    check.set_defaults(_handler=run_check)


def _message(status: UpdateStatus) -> str:
    if status.state == "current":
        return f"HybridOps.Core {status.installed} is current."
    if status.state == "update_available":
        suffix = f"\nRelease: {status.release_url}" if status.release_url else ""
        return f"HybridOps.Core {status.latest} is available (installed {status.installed}).{suffix}"
    if status.state == "unsupported":
        suffix = f"\nRelease: {status.release_url}" if status.release_url else ""
        return (
            f"HybridOps.Core {status.installed} is outside the current release line "
            f"({status.latest}). Update before starting a new deployment.{suffix}"
        )
    if status.state == "development":
        return f"HybridOps.Core {status.installed} is a development build; release comparison skipped."
    if status.state == "offline":
        return "Release status is unavailable. The installed CLI remains usable."
    return "Release status could not be determined."


def run_check(ns: argparse.Namespace) -> int:
    status = check_for_update(root=ns.root, use_cache=not ns.no_cache)
    if ns.json:
        print(json.dumps(status.__dict__, sort_keys=True))
    else:
        print(_message(status))
    return OK
