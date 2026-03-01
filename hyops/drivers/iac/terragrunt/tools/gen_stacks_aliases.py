#!/usr/bin/env python3
"""Generate Terragrunt stack aliases.

purpose: Replace legacy shell helper with a core-native stack alias generator.
Architecture Decision: ADR-N/A (terragrunt stacks aliases)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _path_to_alias(rel_path: Path) -> str:
    name = rel_path.as_posix()

    replacements = (
        ("cloud/", ""),
        ("onprem/", ""),
        ("proxmox", "pve"),
        ("vmware", "vmw"),
        ("azure", "az"),
        ("environments/", ""),
        ("00-foundation-global/", ""),
        ("10-shared-services-global/", ""),
        ("00-foundation/", ""),
        ("10-platform/", ""),
        ("key-vault", "keyvault"),
        ("resource-group", "rg"),
        ("k8s-nodes", "k8s"),
        ("/", "-"),
        ("_", "-"),
    )

    for old, new in replacements:
        name = name.replace(old, new)

    while "--" in name:
        name = name.replace("--", "-")

    return name.strip("-")


def _iter_terragrunt_dirs(live_root: Path) -> list[Path]:
    out: list[Path] = []
    for tg in live_root.rglob("terragrunt.hcl"):
        d = tg.parent
        parts = set(d.parts)
        if ".terragrunt-cache" in parts or ".terraform" in parts:
            continue
        out.append(d)
    return sorted(out)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gen_stacks_aliases",
        description="Generate stacks symlink aliases for Terragrunt live trees.",
    )
    p.add_argument(
        "--live-root",
        required=True,
        help="Path to live root (for example infra/terraform/live-v1).",
    )
    p.add_argument(
        "--stacks-dir",
        default="",
        help="Optional explicit stacks dir; defaults to <live-root>/stacks.",
    )
    p.add_argument("--verbose", action="store_true", help="Print alias mappings.")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    live_root = Path(str(args.live_root or "")).expanduser().resolve()
    if not live_root.exists() or not live_root.is_dir():
        print(f"gen_stacks_aliases: live root not found: {live_root}")
        return 2

    if args.stacks_dir:
        stacks_dir = Path(str(args.stacks_dir)).expanduser().resolve()
    else:
        stacks_dir = (live_root / "stacks").resolve()

    if stacks_dir.exists():
        shutil.rmtree(stacks_dir)
    stacks_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for module_dir in _iter_terragrunt_dirs(live_root):
        rel = module_dir.relative_to(live_root)
        alias = _path_to_alias(rel)
        if not alias:
            continue

        link_path = stacks_dir / alias
        target_rel = Path("..") / rel

        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()

        link_path.symlink_to(target_rel)
        count += 1

        if args.verbose:
            print(f"{alias} -> {rel.as_posix()}")

    print(f"Stacks: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
