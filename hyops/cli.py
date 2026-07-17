"""
purpose: Route `hyops` commands to implementation modules.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import os
import sys

from hyops.runtime.exitcodes import CANCELLED
from hyops.runtime.command_evidence import PythonCommandEvidence, command_evidence_dir
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.init.command import add_init_subparser
from hyops.inventory.command import add_inventory_subparser
from hyops.module.command import add_module_subparser
from hyops.preflight.command import add_preflight_subparser
from hyops.runner.command import add_runner_subparser
from hyops.secrets.command import add_secrets_subparser
from hyops.show.command import add_show_subparser
from hyops.setup.command import add_setup_subparser
from hyops.state.command import add_state_subparser
from hyops.stacks.command import add_stacks_subparser
from hyops.test.command import add_test_subparser
from hyops.terragrunt.command import add_terragrunt_subparser
from hyops.tfc.command import add_tfc_subparser
from hyops.vault.command import add_vault_subparser
from hyops.update.command import add_update_subparser

from hyops.drivers.builtin.register import register_all as register_builtin_drivers
from hyops.drivers.plugins import register_plugins as register_driver_plugins
from hyops.drivers.registry import REGISTRY

from hyops.validators.builtin.register import register_all as register_builtin_validators
from hyops.validators.plugins import register_plugins as register_validator_plugins


_DRIVERS_REGISTERED = False
_VALIDATORS_REGISTERED = False


class _OperatorHelpFormatter(argparse.HelpFormatter):
    """Omit compatibility-only commands from the primary operator view."""

    def _format_action(self, action: argparse.Action) -> str:
        if action.help == argparse.SUPPRESS:
            return ""
        return super()._format_action(action)


def _register_drivers() -> None:
    global _DRIVERS_REGISTERED
    if _DRIVERS_REGISTERED:
        return

    register_builtin_drivers(REGISTRY)

    strict = os.environ.get("HYOPS_STRICT_PLUGINS", "").strip() == "1"
    try:
        register_driver_plugins(REGISTRY)
    except Exception as e:
        if strict:
            raise
        print(f"WARN: driver plugin registration failed: {e}", file=sys.stderr)

    _DRIVERS_REGISTERED = True


def _register_validators() -> None:
    global _VALIDATORS_REGISTERED
    if _VALIDATORS_REGISTERED:
        return

    register_builtin_validators()

    strict = os.environ.get("HYOPS_STRICT_PLUGINS", "").strip() == "1"
    try:
        register_validator_plugins()
    except Exception as e:
        if strict:
            raise
        print(f"WARN: validator plugin registration failed: {e}", file=sys.stderr)

    _VALIDATORS_REGISTERED = True


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hyops",
        add_help=True,
        formatter_class=_OperatorHelpFormatter,
    )
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Stream tool output to terminal while also writing run records.",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable terminal status colours.",
    )
    sp = p.add_subparsers(dest="cmd", required=False, metavar="COMMAND")

    add_init_subparser(sp)
    add_module_subparser(sp)
    add_vault_subparser(sp)
    add_show_subparser(sp)
    add_preflight_subparser(sp)
    add_test_subparser(sp)
    add_runner_subparser(sp)
    add_setup_subparser(sp)
    add_state_subparser(sp)
    add_update_subparser(sp)
    add_secrets_subparser(sp)
    add_inventory_subparser(sp)
    try:
        from hyops.blueprint.command import add_blueprint_subparser
        add_blueprint_subparser(sp)
    except ModuleNotFoundError as e:
        if e.name == "yaml":
            print("WARN: blueprint command disabled; missing dependency: PyYAML", file=sys.stderr)
        else:
            raise
    add_terragrunt_subparser(sp)
    add_tfc_subparser(sp)
    add_stacks_subparser(sp)
    from hyops.commands import apply as cmd_apply
    from hyops.commands import rebuild as cmd_rebuild
    cmd_apply.add_subparser(sp)
    cmd_rebuild.add_subparser(sp)

    return p


def main(argv: list[str] | None = None) -> int:
    _register_drivers()
    _register_validators()

    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    ns = parser.parse_args(argv)

    if getattr(ns, "no_color", False):
        os.environ["NO_COLOR"] = "1"

    from hyops.runtime.terminal import configure_status_streams

    configure_status_streams()

    if getattr(ns, "version", False):
        from hyops import __version__
        print(__version__)
        return 0

    if getattr(ns, "verbose", False):
        os.environ["HYOPS_VERBOSE"] = "1"

    if ns.cmd is None or not hasattr(ns, "_handler"):
        parser.print_help()
        return 2

    from hyops.update.policy import command_requires_supported_release, support_decision

    if command_requires_supported_release(ns):
        decision = support_decision(root=getattr(ns, "root", None))
        if decision.blocked:
            print(
                f"ERR: HybridOps.Core {decision.installed} is no longer supported for "
                f"this operation (minimum {decision.minimum}).",
                file=sys.stderr,
            )
            print("Run: hyops update install", file=sys.stderr)
            return 2
        if decision.state == "grace":
            print(
                f"WARN: Core {decision.installed} requires an update by "
                f"{decision.enforce_after} (minimum {decision.minimum}).",
                file=sys.stderr,
            )

    try:
        if ns.cmd == "preflight":
            paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
            ensure_layout(paths)
            from hyops.runtime.storage import format_runtime_storage_error, require_runtime_writable

            try:
                require_runtime_writable(paths.root)
            except Exception as exc:
                print(f"ERR: {format_runtime_storage_error(exc)}", file=sys.stderr)
                return 2
            evidence_dir = command_evidence_dir(paths.logs_dir, "preflight")
            with PythonCommandEvidence(evidence_dir, command="preflight", argv=argv) as evidence:
                evidence.exit_code = int(ns._handler(ns))
                return evidence.exit_code
        result = int(ns._handler(ns))
        if result == 0:
            from hyops.update.checker import maybe_print_update_notice

            maybe_print_update_notice(ns.cmd)
        return result
    except KeyboardInterrupt:
        print("Cancelled by user.", file=sys.stderr)
        return CANCELLED


if __name__ == "__main__":
    raise SystemExit(main())
