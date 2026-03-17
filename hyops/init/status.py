"""Init status.

purpose: Show readiness markers under `~/.hybridops/meta`.
Architecture Decision: ADR-N/A (init status)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse

from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.state import read_json


def add_init_status_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("status", help="Show target readiness markers.")
    add_init_shared_args(p)
    p.set_defaults(_handler=run)


def run(ns) -> int:
    paths = resolve_runtime_paths(ns.root, getattr(ns, "env", None))
    meta = paths.meta_dir
    if not meta.exists():
        print(f"no runtime meta directory: {meta}")
        return 1

    markers = sorted(meta.glob("*.ready.json"))
    if not markers:
        print("no readiness markers found")
        return 1

    for m in markers:
        try:
            obj = read_json(m)
            status = obj.get("status", "unknown")
            target = obj.get("target", m.name.replace(".ready.json", ""))
            run_id = obj.get("run_id", "-")
            print(f"{target}: {status} (run_id={run_id})")
        except Exception as e:
            print(f"{m.name}: unreadable ({e})")
    return 0
