"""Init shared CLI args.

purpose: Let `hyops init` shared flags be accepted both before and after the
target subcommand.

This allows both:
  - hyops init --env dev azure ...
  - hyops init azure --env dev ...
"""

from __future__ import annotations

import argparse


def add_init_shared_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--non-interactive", action="store_true", help="Fail with guidance instead of prompting.")
    p.add_argument(
        "--with-cli-login",
        action="store_true",
        help="Allow init targets to invoke interactive provider/CLI login flows when needed.",
    )
    p.add_argument(
        "--logout-after",
        action="store_true",
        help="Best-effort logout from provider CLIs after successful init (optional).",
    )
    p.add_argument("--force", action="store_true", help="Overwrite existing generated outputs.")
    p.add_argument("--dry-run", action="store_true", help="Plan actions without applying changes.")
    p.add_argument("--out-dir", default=None, help="Override evidence directory root for this run.")
    p.add_argument("--config", default=None, help="Override target config path.")
    p.add_argument("--vault-file", default=None, help="Override vault file path (where applicable).")
    p.add_argument("--vault-password-file", default=None, help="Path to vault password file.")
    p.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    p.add_argument(
        "--root",
        default=None,
        help="Override runtime root (default: HYOPS_RUNTIME_ROOT or ~/.hybridops).",
    )
    p.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")


__all__ = ["add_init_shared_args"]
