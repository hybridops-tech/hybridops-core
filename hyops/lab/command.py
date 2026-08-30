"""CLI for existing-lab migration intake."""

from __future__ import annotations

import argparse
import json
import shlex
from typing import Any

from hyops.runtime.exitcodes import OPERATOR_ERROR
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.storage import format_runtime_storage_error, require_runtime_writable

from .migration import (
    capture_existing_lab,
    inspect_migration_archive,
    stage_migration_archive,
)


def _add_archive_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--platform",
        required=True,
        choices=("eve-ng", "gns3"),
        help="Source lab platform.",
    )
    parser.add_argument("--archive", required=True, help="Portable lab archive path.")
    parser.add_argument(
        "--node-state",
        default="",
        help="Optional EVE-NG QEMU node-state companion archive.",
    )
    parser.add_argument(
        "--expected-sha256",
        default="",
        help="Expected SHA-256 for the primary archive.",
    )
    parser.add_argument(
        "--node-state-expected-sha256",
        default="",
        help="Expected SHA-256 for the node-state archive.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")


def add_lab_subparser(sp: argparse._SubParsersAction) -> None:
    parser = sp.add_parser("lab", help="Existing lab migration.")
    commands = parser.add_subparsers(dest="lab_cmd", required=True)
    migrate = commands.add_parser(
        "migrate",
        help="Capture, inspect or import a same-platform lab archive.",
    )
    migration_commands = migrate.add_subparsers(dest="migration_cmd", required=True)

    capture_parser = migration_commands.add_parser(
        "capture",
        help="Capture a stopped existing lab through SSH without changing its host.",
    )
    capture_parser.add_argument(
        "--platform",
        required=True,
        choices=("eve-ng", "gns3"),
        help="Source lab platform.",
    )
    capture_parser.add_argument("--host", required=True, help="SSH host or alias.")
    capture_parser.add_argument("--user", default="", help="SSH user.")
    capture_parser.add_argument("--port", type=int, default=22, help="SSH port.")
    capture_parser.add_argument(
        "--identity-file",
        default="",
        help=(
            "Optional SSH private key path. Without it, OpenSSH uses its "
            "configured identities and may prompt for a password."
        ),
    )
    capture_parser.add_argument("--output", required=True, help="Local archive path.")
    capture_parser.add_argument(
        "--become",
        action="store_true",
        help="Read source data through passwordless sudo.",
    )
    capture_parser.add_argument(
        "--include-node-state",
        action="store_true",
        help="Capture stopped EVE-NG QEMU overlays.",
    )
    capture_parser.add_argument(
        "--node-state-output",
        default="",
        help="Optional EVE-NG node-state output path.",
    )
    capture_parser.add_argument(
        "--include-images",
        action="store_true",
        help="Include the GNS3 image library.",
    )
    capture_parser.add_argument("--force", action="store_true", help="Replace outputs.")
    capture_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    capture_parser.set_defaults(_handler=run_capture)

    inspect_parser = migration_commands.add_parser(
        "inspect",
        help="Validate a migration archive without changing runtime state.",
    )
    _add_archive_args(inspect_parser)
    inspect_parser.set_defaults(_handler=run_inspect)

    import_parser = migration_commands.add_parser(
        "import",
        help="Stage a verified archive for restoration by a target blueprint.",
    )
    _add_archive_args(import_parser)
    import_parser.add_argument("--root", default=None, help="Override runtime root.")
    import_parser.add_argument("--env", default=None, help="Runtime environment namespace.")
    import_parser.add_argument("--ref", default="", help="Target blueprint reference.")
    import_parser.add_argument(
        "--file",
        default="",
        help="Explicit runtime blueprint file.",
    )
    import_parser.add_argument(
        "--blueprints-root",
        default="blueprints",
        help="Blueprint root directory.",
    )
    import_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace a different active migration record.",
    )
    import_parser.set_defaults(_handler=run_import)


def _print_inspection(report: dict[str, Any]) -> None:
    archive = report["archive"]
    print(f"migration platform={report['platform']} status={report['status']}")
    print(f"archive={archive['path']}")
    print(f"sha256={archive['sha256']}")
    print(f"definitions={report['definition_count']} members={archive['member_count']}")
    print(f"image_references={len(report['image_references'])}")
    node_state = report.get("node_state")
    if isinstance(node_state, dict):
        print(f"node_state=present overlays={node_state['overlay_count']}")
    else:
        print("node_state=absent")
    for warning in report.get("warnings") or []:
        print(f"WARN: {warning}")


def run_capture(ns) -> int:
    try:
        report = capture_existing_lab(
            platform=ns.platform,
            host=ns.host,
            output=ns.output,
            user=ns.user,
            port=ns.port,
            identity_file=ns.identity_file or None,
            become=ns.become,
            include_node_state=ns.include_node_state,
            node_state_output=ns.node_state_output or None,
            include_images=ns.include_images,
            force=ns.force,
        )
    except (OSError, ValueError) as exc:
        print(f"ERR: lab migration capture failed: {exc}")
        return OPERATOR_ERROR
    if ns.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_inspection(report)
    return 0


def run_inspect(ns) -> int:
    try:
        report = inspect_migration_archive(
            platform=ns.platform,
            archive=ns.archive,
            node_state=ns.node_state or None,
            expected_sha256=ns.expected_sha256,
            node_state_expected_sha256=ns.node_state_expected_sha256,
        )
    except (OSError, ValueError) as exc:
        print(f"ERR: lab migration inspection failed: {exc}")
        return OPERATOR_ERROR
    if ns.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_inspection(report)
    return 0


def run_import(ns) -> int:
    try:
        require_runtime_selection(
            ns.root,
            ns.env,
            command_label="hyops lab migrate import",
        )
        paths = resolve_runtime_paths(ns.root, ns.env)
        ensure_layout(paths)
        require_runtime_writable(paths.root)
        from hyops.blueprint.command import (
            _enforce_runtime_blueprint_file_scope,
            _resolve_and_validate,
        )

        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="lab migration import",
        )
        payload = _resolve_and_validate(ns)
        record = stage_migration_archive(
            paths=paths,
            payload=payload,
            platform=ns.platform,
            archive=ns.archive,
            node_state=ns.node_state or None,
            expected_sha256=ns.expected_sha256,
            node_state_expected_sha256=ns.node_state_expected_sha256,
            force=ns.force,
        )
    except (OSError, ValueError) as exc:
        detail = format_runtime_storage_error(exc) if isinstance(exc, OSError) else str(exc)
        print(f"ERR: lab migration import failed: {detail}")
        return OPERATOR_ERROR

    if ns.json:
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    print(
        f"migration platform={record['platform']} "
        f"blueprint={record['blueprint_ref']} status=ready"
    )
    print(f"archive={record['archive']['path']}")
    print(f"sha256={record['archive']['sha256']}")
    print(f"definitions={record['definition_count']}")
    for warning in record.get("warnings") or []:
        print(f"WARN: {warning}")
    if ns.env:
        selection = ["--env", ns.env]
    elif ns.root:
        selection = ["--root", ns.root]
    else:
        selection = []
    selector = ["--file", ns.file] if ns.file else ["--ref", record["blueprint_ref"]]
    command = [
        "hyops",
        "blueprint",
        "deploy",
        *selection,
        *selector,
        "--execute",
        "--restore-labs",
    ]
    print(f"restore: {shlex.join(command)}")
    return 0
