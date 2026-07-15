"""
purpose: Expose explicit Core release checks through the HybridOps CLI.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

from hyops.runtime.exitcodes import OK
from hyops.update.checker import UpdateStatus, check_for_update
from hyops.update.installer import install_release


def add_update_subparser(sp: argparse._SubParsersAction) -> None:
    parser = sp.add_parser("update", help="Check Core release status.")
    commands = parser.add_subparsers(dest="update_cmd", required=True)
    check = commands.add_parser("check", help="Compare the installed and current releases.")
    check.add_argument("--no-cache", action="store_true", help="Query the release service now.")
    check.add_argument("--json", action="store_true", help="Print machine-readable output.")
    check.add_argument("--root", help="Runtime root used for the update-check cache.")
    check.set_defaults(_handler=run_check)
    install = commands.add_parser("install", help="Install the current Core release.")
    install.add_argument("--yes", action="store_true", help="Install without confirmation.")
    install.add_argument("--root", help="Runtime root used for release checks.")
    install.set_defaults(_handler=run_install)


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


def run_install(ns: argparse.Namespace) -> int:
    status = check_for_update(root=ns.root, use_cache=False, timeout=10.0)
    if status.state == "current":
        print(f"HybridOps.Core {status.installed} is current.")
        return OK
    if status.state not in {"update_available", "unsupported"} or not status.latest:
        print("ERR: a current release could not be resolved.", file=sys.stderr)
        return 2
    if not status.release_url:
        print("ERR: the release download location is unavailable.", file=sys.stderr)
        return 2
    if not ns.yes:
        answer = input(f"Install HybridOps.Core {status.latest}? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Update cancelled.")
            return 2
    try:
        result = install_release(status.latest, status.release_url)
    except (OSError, ValueError, requests.RequestException) as exc:
        print(f"ERR: update failed: {exc}", file=sys.stderr)
        return 2
    return result
