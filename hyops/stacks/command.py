"""Stacks command.

purpose: Expose stack alias management as a stable hyops CLI surface.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse

from hyops.drivers.iac.terragrunt.tools.gen_stacks_aliases import main as gen_aliases_main
from hyops.runtime.exitcodes import INTERNAL_ERROR


def add_stacks_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("stacks", help="Terragrunt stack alias utilities.")
    ssp = p.add_subparsers(dest="stacks_cmd", required=True)

    q = ssp.add_parser("aliases", help="Generate stacks aliases from a Terragrunt live root.")
    q.add_argument("--live-root", required=True, help="Path to live root, for example infra/terraform/live-v1.")
    q.add_argument("--stacks-dir", default="", help="Optional explicit stacks dir; defaults to <live-root>/stacks.")
    q.add_argument("--verbose", action="store_true", help="Print alias mappings.")
    q.set_defaults(_handler=run_aliases)


def run_aliases(ns) -> int:
    argv = ["--live-root", str(ns.live_root)]
    if str(ns.stacks_dir or "").strip():
        argv += ["--stacks-dir", str(ns.stacks_dir)]
    if bool(getattr(ns, "verbose", False)):
        argv.append("--verbose")

    try:
        return int(gen_aliases_main(argv))
    except SystemExit as e:
        try:
            return int(e.code)
        except Exception:
            return INTERNAL_ERROR
    except Exception as e:
        print(f"ERR: failed to generate stack aliases: {e}")
        return INTERNAL_ERROR


__all__ = ["add_stacks_subparser", "run_aliases"]
