"""Inventory commands.

purpose: Expose inventory helper operations through hyops CLI.
Architecture Decision: ADR-N/A (inventory command)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

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


def _infer_runtime_root_from_dataset(dataset: str) -> Path | None:
    raw = str(dataset or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    parts = p.parts
    try:
        idx = parts.index(".hybridops")
    except ValueError:
        return None
    # Expect: ... /.hybridops / envs / <env> / ...
    if len(parts) <= idx + 3:
        return None
    if parts[idx + 1] != "envs":
        return None
    return Path(*parts[: idx + 4]).resolve()


def _hydrate_netbox_env_for_sync(*, dataset: str) -> None:
    """Best-effort hydrate NETBOX_* for direct inventory sync commands.

    Hooks already do this. Direct CLI sync should behave similarly by inferring
    the runtime root from `--dataset` when possible, then falling back to the
    standard runtime-root resolver.
    """
    try:
        from hyops.runtime.netbox_env import hydrate_netbox_env
        from hyops.runtime.root import resolve_runtime_root
    except Exception:
        return

    runtime_root = _infer_runtime_root_from_dataset(dataset)
    if runtime_root is None:
        try:
            runtime_root = resolve_runtime_root()
        except Exception:
            return

    try:
        warnings, _missing = hydrate_netbox_env(os.environ, runtime_root)
    except Exception:
        return
    for w in warnings:
        text = str(w or "").strip()
        if text:
            print(f"WARN: {text}")


def add_inventory_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("inventory", help="Inventory helper commands.")
    ssp = p.add_subparsers(dest="inventory_cmd", required=True)

    q = ssp.add_parser("export-infra", help="Dispatch infrastructure exports for NetBox tooling.")
    q.add_argument("--target", default=None, help="Export target.")
    q.add_argument("--platform", default=None, help="Logical platform scope (for example: onprem, cloud).")
    q.add_argument("--provider", default=None, help="Provider/runtime name (for example: proxmox, azure, gcp).")
    q.add_argument("--list-targets", action="store_true", help="List available targets and exit.")
    q.add_argument("--dry-run", action="store_true", help="Do not write VM dataset and inventories.")
    q.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate VM dataset contract after discovery and exit.",
    )
    q.add_argument(
        "--terragrunt-root",
        default=None,
        help="Override Terragrunt root directory for discovery.",
    )
    q.add_argument("--only-module", action="append", default=[], help="Relative module path under terragrunt root.")
    q.add_argument("--changed-only", action="store_true", help="Skip processing when outputs are unchanged.")
    q.set_defaults(_handler=run_export_infra)

    s = ssp.add_parser("sync-netbox", help="Import exported dataset into NetBox (VM inventory or IPAM).")
    s.add_argument("--dry-run", action="store_true", help="Do not modify NetBox; print intended actions.")
    s.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate dataset contract and exit without NetBox API calls.",
    )
    s.add_argument("--dataset", default=None, help="Override input dataset path (.json or .csv).")
    s.add_argument(
        "--kind",
        choices=["auto", "vms", "ipam-prefixes"],
        default="auto",
        help="Dataset kind. 'auto' infers from dataset path/name (default).",
    )
    s.add_argument(
        "--ipam-target",
        choices=["onprem-sdn", "cloud"],
        default="onprem-sdn",
        help="IPAM import mode when syncing prefix datasets (default: onprem-sdn).",
    )
    s.add_argument(
        "--destroy-sync",
        action="store_true",
        help="VM dataset only: retire/delete listed VMs in NetBox (destroy path) instead of ensuring inventory.",
    )
    s.add_argument(
        "--hard-delete",
        action="store_true",
        help="With --destroy-sync, delete VMs from NetBox instead of soft-retiring them.",
    )
    s.set_defaults(_handler=run_sync_netbox)


def run_export_infra(ns) -> int:
    try:
        from hyops.drivers.inventory.netbox.tools.export_infra import main as export_infra_main
    except ModuleNotFoundError as e:
        print(f"ERR: inventory export unavailable; missing dependency: {e.name}")
        return INTERNAL_ERROR

    argv: list[str] = []
    if str(ns.target or "").strip():
        argv += ["--target", str(ns.target)]
    if str(ns.platform or "").strip():
        argv += ["--platform", str(ns.platform)]
    if str(ns.provider or "").strip():
        argv += ["--provider", str(ns.provider)]
    if bool(getattr(ns, "list_targets", False)):
        argv.append("--list-targets")
    if bool(getattr(ns, "dry_run", False)):
        argv.append("--dry-run")
    if bool(getattr(ns, "validate_only", False)):
        argv.append("--validate-only")
    if str(ns.terragrunt_root or "").strip():
        argv += ["--terragrunt-root", str(ns.terragrunt_root)]
    for mod in list(getattr(ns, "only_module", []) or []):
        if str(mod or "").strip():
            argv += ["--only-module", str(mod)]
    if bool(getattr(ns, "changed_only", False)):
        argv.append("--changed-only")

    try:
        return int(export_infra_main(argv))
    except SystemExit as e:
        return _exit_code_from_system_exit(e)
    except Exception as e:
        print(f"ERR: failed to export inventory dataset: {e}")
        return INTERNAL_ERROR


def run_sync_netbox(ns) -> int:
    argv: list[str] = []
    if bool(getattr(ns, "dry_run", False)):
        argv.append("--dry-run")
    if bool(getattr(ns, "validate_only", False)):
        argv.append("--validate-only")
    dataset = str(ns.dataset or "").strip()
    if dataset:
        argv += ["--dataset", dataset]

    if not bool(getattr(ns, "validate_only", False)):
        _hydrate_netbox_env_for_sync(dataset=dataset)

    kind = str(getattr(ns, "kind", "auto") or "auto").strip().lower()
    if kind == "auto":
        dataset_hint = dataset.lower()
        dataset_name = Path(dataset_hint).name if dataset_hint else ""
        if "ipam-prefixes" in dataset_name or "/network/" in dataset_hint or dataset_hint.endswith("/network"):
            kind = "ipam-prefixes"
        else:
            kind = "vms"

    if kind == "ipam-prefixes":
        try:
            from hyops.drivers.inventory.netbox.tools.import_prefixes_to_netbox import (
                main as sync_ipam_main,
            )
        except ModuleNotFoundError as e:
            print(f"ERR: inventory IPAM sync unavailable; missing dependency: {e.name}")
            return INTERNAL_ERROR

        argv += ["--target", str(getattr(ns, "ipam_target", "onprem-sdn") or "onprem-sdn")]
        argv.append("--no-emit")
        try:
            return int(sync_ipam_main(argv))
        except SystemExit as e:
            return _exit_code_from_system_exit(e)
        except Exception as e:
            print(f"ERR: failed to sync NetBox IPAM dataset: {e}")
            return INTERNAL_ERROR

    try:
        from hyops.drivers.inventory.netbox.tools.import_infra_to_netbox import (
            main as sync_netbox_main,
        )
    except ModuleNotFoundError as e:
        print(f"ERR: inventory sync unavailable; missing dependency: {e.name}")
        return INTERNAL_ERROR

    if bool(getattr(ns, "destroy_sync", False)):
        argv.append("--destroy-sync")
    if bool(getattr(ns, "hard_delete", False)):
        argv.append("--hard-delete")

    try:
        return int(sync_netbox_main(argv))
    except SystemExit as e:
        return _exit_code_from_system_exit(e)
    except Exception as e:
        print(f"ERR: failed to sync NetBox inventory: {e}")
        return INTERNAL_ERROR


__all__ = ["add_inventory_subparser", "run_export_infra", "run_sync_netbox"]
