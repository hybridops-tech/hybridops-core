"""Init shared CLI args.

purpose: Let `hyops init` shared flags be accepted both before and after the
target subcommand.

This allows both:
  - hyops init --env dev azure ...
  - hyops init azure --env dev ...
"""

from __future__ import annotations

import argparse


def add_init_shared_args(p: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    # Child defaults must not overwrite options already parsed by `hyops init`.
    value_default = argparse.SUPPRESS if suppress_defaults else None
    flag_default = argparse.SUPPRESS if suppress_defaults else False
    p.add_argument("--non-interactive", action="store_true", default=flag_default, help="Fail with guidance instead of prompting.")
    p.add_argument(
        "--with-cli-login",
        action="store_true", default=flag_default,
        help="Allow init targets to invoke interactive provider/CLI login flows when needed.",
    )
    p.add_argument(
        "--logout-after",
        action="store_true", default=flag_default,
        help="Best-effort logout from provider CLIs after successful init (optional).",
    )
    p.add_argument(
        "--force",
        action="store_true", default=flag_default,
        help="Init only: overwrite generated config templates and outputs where the target supports it.",
    )
    p.add_argument("--dry-run", action="store_true", default=flag_default, help="Plan actions without applying changes.")
    p.add_argument("--out-dir", default=value_default, help="Override evidence directory root for this run.")
    p.add_argument("--config", default=value_default, help="Override target config path.")
    p.add_argument("--vault-file", default=value_default, help="Override vault file path (where applicable).")
    p.add_argument("--vault-password-file", default=value_default, help="Path to vault password file.")
    p.add_argument("--vault-password-command", default=value_default, help="Command to output vault password.")
    p.add_argument(
        "--root",
        default=value_default,
        help="Override runtime root (default: HYOPS_RUNTIME_ROOT or ~/.hybridops).",
    )
    p.add_argument("--env", default=value_default, help="Runtime environment namespace (e.g. dev, shared).")


__all__ = ["add_init_shared_args"]
