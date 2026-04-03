"""Init command router.

purpose: Implement `hyops init ...` command family and target dispatch.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse

from hyops.init.status import add_init_status_subparser
from hyops.init.shared_args import add_init_shared_args
from hyops.init.targets import aws, azure, gcp, hashicorp_vault, hetzner, proxmox, terraform_cloud


def add_init_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("init", help="Prepare runtime and prerequisites for a target.")

    add_init_shared_args(p)

    tsp = p.add_subparsers(dest="target", required=True)

    proxmox.add_subparser(tsp)
    terraform_cloud.add_subparser(tsp)
    azure.add_subparser(tsp)
    gcp.add_subparser(tsp)
    aws.add_subparser(tsp)
    hetzner.add_subparser(tsp)
    hashicorp_vault.add_subparser(tsp)

    add_init_status_subparser(tsp)

    p.set_defaults(_handler=_dispatch_init)


def _dispatch_init(ns) -> int:
    if not hasattr(ns, "_handler"):
        raise SystemExit(2)
    return int(ns._handler(ns))


__all__ = ["add_init_subparser"]
