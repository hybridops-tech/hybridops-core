#!/usr/bin/env python3
"""Configure Terraform Cloud workspace execution mode (non-fatal by default).

purpose: Replace legacy shell helper with a core-native tool for workspace policy setup.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hyops.drivers.iac.terraform_cloud.workspace import (
    default_workspace_description,
    ensure_workspace_execution_mode,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="configure_workspace_execution_mode",
        description="Ensure Terraform Cloud workspace execution mode.",
    )
    p.add_argument("workspace_name", help="Terraform Cloud workspace name.")
    p.add_argument("org", nargs="?", default="hybridops-studio", help="Terraform Cloud organization.")
    p.add_argument(
        "execution_mode",
        nargs="?",
        default="local",
        choices=("local", "remote", "agent"),
        help="Execution mode.",
    )
    p.add_argument("--host", default="app.terraform.io", help="Terraform Cloud host.")
    p.add_argument(
        "--credentials-file",
        default="~/.terraform.d/credentials.tfrc.json",
        help="Terraform credentials file path.",
    )
    p.add_argument(
        "--description",
        default="",
        help="Optional workspace description override.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero on policy/tooling errors.",
    )
    p.add_argument("--json", action="store_true", help="Emit result as JSON.")
    return p


def _log_human(result: dict[str, object]) -> None:
    status = str(result.get("status") or "unknown")
    msg = str(result.get("message") or "")
    ws = str(result.get("workspace_name") or "")
    mode = str(result.get("execution_mode") or "")

    if status == "updated":
        print(f"[Workspace Config] Updated: {ws} -> {mode}")
        if msg:
            print(f"[Workspace Config] {msg}")
        return

    if status == "unchanged":
        print(f"[Workspace Config] Already configured: {ws} ({mode})")
        return

    print(f"[Workspace Config] Non-fatal: {status}")
    if msg:
        print(f"[Workspace Config] {msg}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    description = str(args.description or "").strip() or default_workspace_description(args.execution_mode)

    result = ensure_workspace_execution_mode(
        host=str(args.host or "app.terraform.io").strip() or "app.terraform.io",
        org=str(args.org or "").strip(),
        workspace_name=str(args.workspace_name or "").strip(),
        execution_mode=str(args.execution_mode or "").strip(),
        credentials_file=Path(str(args.credentials_file or "")).expanduser().resolve(),
        description=description,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _log_human(result)

    ok = bool(result.get("ok"))
    if ok:
        return 0

    if args.strict:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
