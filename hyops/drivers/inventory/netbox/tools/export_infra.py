#!/usr/bin/env python3
# purpose: Dispatch infrastructure exports for NetBox tooling.
# maintainer: HybridOps.Studio

from __future__ import annotations

import argparse
import os
import signal
import sys
from dataclasses import replace
from pathlib import Path
from typing import Final

from .paths import RUNTIME_ROOT
from .terraform_export import ExportConfig, run_export


signal.signal(signal.SIGPIPE, signal.SIG_IGN)

DEFAULT_TARGET: Final[str] = "onprem-proxmox"


def _target_env_key(target: str) -> str:
    token = target.upper().replace("-", "_")
    return f"HYOPS_TERRAGRUNT_ROOT_{token}"


def _root_from_env(target: str, default_rel: str) -> Path:
    env_key = _target_env_key(target)
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (RUNTIME_ROOT / p).resolve()
    return (RUNTIME_ROOT / default_rel).resolve()


def _build_configs() -> dict[str, ExportConfig]:
    base_logs = RUNTIME_ROOT / "logs" / "netbox" / "terraform"
    base_artifacts = RUNTIME_ROOT / "artifacts" / "netbox" / "terraform"

    return {
        "onprem-proxmox": ExportConfig(
            target="onprem-proxmox",
            terragrunt_root=_root_from_env("onprem-proxmox", "work/live/onprem/proxmox"),
            logs_root=base_logs / "onprem" / "proxmox",
            artifacts_root=base_artifacts / "onprem" / "proxmox",
            default_cluster="onprem-core",
            cluster_prefix="onprem",
            exclude_patterns=("shared",),
        ),
        "onprem-vmware": ExportConfig(
            target="onprem-vmware",
            terragrunt_root=_root_from_env("onprem-vmware", "work/live/onprem/vmware"),
            logs_root=base_logs / "onprem" / "vmware",
            artifacts_root=base_artifacts / "onprem" / "vmware",
            default_cluster="onprem-vmware-core",
            cluster_prefix="onprem-vmware",
            exclude_patterns=("shared",),
        ),
        "cloud-azure": ExportConfig(
            target="cloud-azure",
            terragrunt_root=_root_from_env("cloud-azure", "work/live/cloud/azure"),
            logs_root=base_logs / "cloud" / "azure",
            artifacts_root=base_artifacts / "cloud" / "azure",
            default_cluster="cloud-azure-core",
            cluster_prefix="cloud-azure",
            exclude_patterns=("shared",),
        ),
        "cloud-gcp": ExportConfig(
            target="cloud-gcp",
            terragrunt_root=_root_from_env("cloud-gcp", "work/live/cloud/gcp"),
            logs_root=base_logs / "cloud" / "gcp",
            artifacts_root=base_artifacts / "cloud" / "gcp",
            default_cluster="cloud-gcp-core",
            cluster_prefix="cloud-gcp",
            exclude_patterns=("shared",),
        ),
        "cloud-hetzner": ExportConfig(
            target="cloud-hetzner",
            terragrunt_root=_root_from_env("cloud-hetzner", "work/live/cloud/hetzner"),
            logs_root=base_logs / "cloud" / "hetzner",
            artifacts_root=base_artifacts / "cloud" / "hetzner",
            default_cluster="cloud-hetzner-core",
            cluster_prefix="cloud-hetzner",
            exclude_patterns=("shared",),
        ),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    configs = _build_configs()
    targets = sorted(configs.keys())

    parser = argparse.ArgumentParser(
        prog=Path(__file__).name,
        description="Dispatch infrastructure exports for NetBox tooling.",
    )

    parser.add_argument("--target", choices=targets, help=f"Export target (default: {DEFAULT_TARGET}).")
    parser.add_argument(
        "--platform",
        help="Logical platform scope (for example: onprem, cloud). Used with --provider if --target is not given.",
    )
    parser.add_argument(
        "--provider",
        help="Provider/runtime name (for example: proxmox, vmware, azure, gcp). Used with --platform if --target is not given.",
    )
    parser.add_argument("--list-targets", action="store_true", help="List available targets and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write exported datasets.")
    parser.add_argument("--validate-only", action="store_true", help="Validate VM dataset contract after discovery and exit.")
    parser.add_argument(
        "--terragrunt-root",
        help="Override Terragrunt root directory for discovery. Default comes from HYOPS_TERRAGRUNT_ROOT_* env or runtime root.",
    )
    parser.add_argument("--only-module", action="append", default=[], help="Relative module path under terragrunt root. Repeatable.")
    parser.add_argument("--changed-only", action="store_true", help="Skip processing when outputs are unchanged.")

    return parser.parse_args(argv)


def _resolve_target(args: argparse.Namespace, configs: dict[str, ExportConfig]) -> str:
    if args.list_targets:
        for name in sorted(configs.keys()):
            print(name)
        raise SystemExit(0)

    if args.target:
        return args.target

    if args.platform and args.provider:
        candidate = f"{args.platform}-{args.provider}"
        if candidate in configs:
            return candidate
        print(f"export_infra: unsupported platform/provider combination: {candidate}", file=sys.stderr)
        print(f"export_infra: known targets: {', '.join(sorted(configs.keys()))}", file=sys.stderr)
        raise SystemExit(2)

    return DEFAULT_TARGET


def _resolve_default_root(cfg: ExportConfig) -> ExportConfig:
    if cfg.terragrunt_root.exists():
        return cfg

    cwd = Path.cwd().resolve()
    if (cwd / "terragrunt.hcl").exists():
        return replace(cfg, terragrunt_root=cwd)

    return cfg


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configs = _build_configs()
    target = _resolve_target(args, configs)

    cfg = configs[target]
    if args.terragrunt_root:
        cfg = replace(cfg, terragrunt_root=Path(args.terragrunt_root).resolve())
    else:
        cfg = _resolve_default_root(cfg)

    if args.changed_only:
        cfg = replace(cfg, changed_only=True)

    return run_export(args, cfg)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except BrokenPipeError:
        raise SystemExit(0)
