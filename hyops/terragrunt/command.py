"""Terragrunt helper commands.

purpose: Expose Terragrunt helper tooling through hyops CLI.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse

from hyops.drivers.iac.terragrunt.tools.validate_proxmox_sdn_vnets import (
    main as validate_proxmox_sdn_vnets_main,
)
from hyops.runtime.exitcodes import INTERNAL_ERROR


def _exit_code_from_system_exit(exc: SystemExit) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, bool):
        return int(code)
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        try:
            return int(code)
        except ValueError:
            return INTERNAL_ERROR
    return INTERNAL_ERROR


def add_terragrunt_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("terragrunt", help="Terragrunt helper tools.")
    ssp = p.add_subparsers(dest="terragrunt_cmd", required=True)

    q = ssp.add_parser(
        "validate-proxmox-sdn-vnets",
        help="Validate Proxmox SDN custom VNet contract.",
    )
    q.add_argument("--file", default="", help="Path to JSON file (overrides env).")
    q.add_argument("--json", default="", help="Inline JSON payload (overrides env).")
    q.add_argument("--strict-empty", action="store_true", help="Fail when no custom payload is provided.")
    q.set_defaults(_handler=run_validate_proxmox_sdn_vnets)


def run_validate_proxmox_sdn_vnets(ns) -> int:
    argv: list[str] = []
    if str(ns.file or "").strip():
        argv += ["--file", str(ns.file)]
    if str(ns.json or "").strip():
        argv += ["--json", str(ns.json)]
    if bool(getattr(ns, "strict_empty", False)):
        argv.append("--strict-empty")

    try:
        return int(validate_proxmox_sdn_vnets_main(argv))
    except SystemExit as exc:
        return _exit_code_from_system_exit(exc)
    except Exception as exc:
        print(f"ERR: failed to validate Proxmox SDN vnets: {exc}")
        return INTERNAL_ERROR


__all__ = ["add_terragrunt_subparser", "run_validate_proxmox_sdn_vnets"]

