"""CLI for existing-lab migration intake."""

from __future__ import annotations

import argparse
import json
import shlex
import time
from typing import Any

from hyops.runtime.exitcodes import OPERATOR_ERROR
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.progress import ProgressDisplay
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.storage import format_runtime_storage_error, require_runtime_writable

from .migration import (
    _format_bytes,
    capture_existing_lab,
    inspect_migration_archive,
    stage_migration_archive,
)


_CAPTURE_LABELS = {
    "assessment": "Assessing source",
    "lab_definitions": "Lab definitions",
    "gns3_projects": "GNS3 projects",
    "containerlab_source": "Containerlab source",
    "node_state": "Node state",
    "referenced_images": "Referenced images",
    "verification": "Archive verification",
}

_IMPORT_LABELS = {
    "lab_definitions": "Lab definitions",
    "node_state": "Node state",
    "referenced_images": "Referenced images",
}


def _concise_bytes(value: int | float) -> str:
    return _format_bytes(max(0, int(value))).split(" (", 1)[0]


def _concise_rate(value: int | float) -> str:
    return f"{_concise_bytes(value)}/s"


def _concise_duration(value: int | float) -> str:
    seconds = max(0, int(value))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


class _CaptureProgress:
    def __init__(self) -> None:
        self.display = ProgressDisplay(show_elapsed=False)
        self._plain_last: dict[str, float] = {}
        self._verification_started = 0.0

    def __call__(self, event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or "")
        if phase == "assessment_started":
            print("assessing source and requested capture streams", flush=True)
            return
        if phase == "assessment_finished":
            print("source assessment:")
            print(f"  lab definitions: {_concise_bytes(event['primary_bytes'])}")
            if int(event.get("node_state_bytes") or 0) > 0:
                print(f"  node state: {_concise_bytes(event['node_state_bytes'])}")
            if int(event.get("image_bytes") or 0) > 0:
                print(f"  referenced images: {_concise_bytes(event['image_bytes'])}")
            return

        stage = str(event.get("stage") or "capture")
        label = _CAPTURE_LABELS.get(stage, stage.replace("_", " ").title())
        key = f"lab-migration-{stage}"
        written = int(event.get("bytes_written") or 0)
        elapsed = float(event.get("elapsed_seconds") or 0.0)
        rate = float(event.get("bytes_per_second") or 0.0)

        if phase == "stream_started":
            expected = int(event.get("expected_source_bytes") or 0)
            source = f"  source {_concise_bytes(expected)}" if expected else ""
            self.display.start(
                key,
                f"{label}{source}",
                plain=(f"capture={stage} status=running source_bytes={expected}"),
            )
            self._plain_last[key] = 0.0
            return

        if phase == "stream_progress":
            current = f"{label}  {_concise_bytes(written)}  {_concise_rate(rate)}"
            self.display.update(key, current)
            last = self._plain_last.get(key, 0.0)
            if not self.display.enabled and elapsed - last >= 30.0:
                print(
                    f"capture={stage} status=running bytes={written} "
                    f"rate_bps={int(rate)} elapsed_s={int(elapsed)}",
                    flush=True,
                )
                self._plain_last[key] = elapsed
            return

        if phase == "stream_finished":
            status = str(event.get("status") or "failed")
            self.display.finish(
                key,
                label,
                status,
                plain=(
                    f"capture={stage} status={status} bytes={written} "
                    f"elapsed_s={int(elapsed)}"
                ),
                detail=(
                    f"{_concise_duration(elapsed)}  "
                    f"{_concise_bytes(written)}  {_concise_rate(rate)}"
                ),
            )
            self._plain_last.pop(key, None)
            return

        if phase == "verification_started":
            self._verification_started = time.monotonic()
            self.display.start(
                key,
                label,
                plain="capture=verification status=running",
            )
            return

        if phase == "verification_finished":
            status = str(event.get("status") or "failed")
            elapsed = (
                time.monotonic() - self._verification_started
                if self._verification_started
                else 0.0
            )
            self.display.finish(
                key,
                label,
                status,
                plain=f"capture=verification status={status}",
                detail=_concise_duration(elapsed),
            )
            self._verification_started = 0.0


class _ImportProgress:
    def __init__(self) -> None:
        self.display = ProgressDisplay(show_elapsed=False)
        self._plain_last: dict[str, float] = {}

    def __call__(self, event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or "")
        if phase in {"import_verification_started", "import_verification_finished"}:
            key = "lab-migration-import-verification"
            label = "Bundle verification"
            if phase == "import_verification_started":
                self.display.start(
                    key,
                    label,
                    plain="import=verification status=running",
                )
                return
            status = str(event.get("status") or "failed")
            self.display.finish(
                key,
                label,
                status,
                plain=f"import=verification status={status}",
            )
            return

        stage = str(event.get("stage") or "archive")
        label = _IMPORT_LABELS.get(stage, stage.replace("_", " ").title())
        key = f"lab-migration-import-{stage}"
        written = int(event.get("bytes_written") or 0)
        total = int(event.get("total_bytes") or 0)
        elapsed = float(event.get("elapsed_seconds") or 0.0)
        rate = float(event.get("bytes_per_second") or 0.0)

        if phase == "stage_started":
            self.display.start(
                key,
                label,
                plain=f"import={stage} status=running bytes_total={total}",
            )
            self._plain_last[key] = 0.0
            return

        if phase == "stage_progress":
            current = f"{label}  {_concise_bytes(written)}/{_concise_bytes(total)}"
            if rate > 0:
                current += f"  {_concise_rate(rate)}"
            self.display.update(key, current)
            last = self._plain_last.get(key, 0.0)
            if not self.display.enabled and elapsed - last >= 30.0:
                print(
                    f"import={stage} status=running bytes={written} "
                    f"total_bytes={total} rate_bps={int(rate)} "
                    f"elapsed_s={int(elapsed)}",
                    flush=True,
                )
                self._plain_last[key] = elapsed
            return

        if phase == "stage_verifying":
            self.display.update(key, f"Verifying {label.lower()}")
            if not self.display.enabled:
                print(f"import={stage} status=verifying", flush=True)
            return

        if phase == "stage_finished":
            status = str(event.get("status") or "failed")
            detail = "already staged" if status == "skipped" else _concise_bytes(written)
            self.display.finish(
                key,
                label,
                status,
                plain=(
                    f"import={stage} status={status} bytes={written} "
                    f"elapsed_s={int(elapsed)}"
                ),
                detail=detail,
            )
            self._plain_last.pop(key, None)


def _add_archive_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--platform",
        required=True,
        choices=("eve-ng", "gns3", "containerlab"),
        help="Source lab platform.",
    )
    parser.add_argument("--archive", required=True, help="Portable lab archive path.")
    parser.add_argument(
        "--node-state",
        default="",
        help="Optional EVE-NG QEMU node-state companion archive.",
    )
    parser.add_argument(
        "--images",
        default="",
        help="Optional EVE-NG referenced-image companion archive.",
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
    parser.add_argument(
        "--images-expected-sha256",
        default="",
        help="Expected SHA-256 for the image archive.",
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
        help="Capture an existing lab through SSH without changing its source tree.",
    )
    capture_parser.add_argument(
        "--platform",
        required=True,
        choices=("eve-ng", "gns3", "containerlab"),
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
        "--source-root",
        default="",
        help="Authoritative source directory for Containerlab capture.",
    )
    capture_parser.add_argument(
        "--topology-relpath",
        default="lab.clab.yml",
        help="Containerlab topology path relative to --source-root.",
    )
    capture_parser.add_argument(
        "--source-labdir-base",
        default="",
        help=(
            "Optional native labdir base used by the existing Containerlab host. "
            "Omit it to use Containerlab's default."
        ),
    )
    capture_parser.add_argument(
        "--target-labdir-base",
        default="/var/lib/hybridops/containerlab/labdirs",
        help="Native labdir base declared by the target Containerlab blueprint.",
    )
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
        "--guest-quiesced",
        action="store_true",
        help=(
            "Confirm EVE-NG guests were shut down inside the guest before "
            "node-state capture."
        ),
    )
    capture_parser.add_argument(
        "--node-state-output",
        default="",
        help="Optional EVE-NG node-state output path.",
    )
    capture_parser.add_argument(
        "--include-images",
        action="store_true",
        help=(
            "Capture referenced EVE-NG base images as a companion archive, "
            "or include the GNS3 image library."
        ),
    )
    capture_parser.add_argument(
        "--images-output",
        default="",
        help="Optional EVE-NG referenced-image output path.",
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
    import_parser.add_argument(
        "--env", default=None, help="Runtime environment namespace."
    )
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
        consistency = str(node_state.get("capture_consistency") or "unrecorded")
        print(
            f"node_state=present overlays={node_state['overlay_count']} "
            f"consistency={consistency}"
        )
    else:
        print("node_state=absent")
    images = report.get("images")
    if isinstance(images, dict):
        print(f"images=present referenced={images['image_count']}")
    elif report.get("images_included"):
        print("images=included")
    else:
        print("images=absent")
    containerlab = report.get("containerlab")
    if isinstance(containerlab, dict):
        print(f"topology={containerlab['topology_relpath']}")
        print(
            "native_config_save="
            f"{'ok' if containerlab.get('native_config_save_rc') == 0 else 'unavailable'}"
        )
    for warning in report.get("warnings") or []:
        print(f"WARN: {warning}")


def run_capture(ns) -> int:
    progress = None if ns.json else _CaptureProgress()
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
            guest_quiesced=ns.guest_quiesced,
            node_state_output=ns.node_state_output or None,
            include_images=ns.include_images,
            images_output=ns.images_output or None,
            source_root=ns.source_root,
            topology_relpath=ns.topology_relpath,
            source_labdir_base=ns.source_labdir_base,
            target_labdir_base=ns.target_labdir_base,
            force=ns.force,
            progress=progress,
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
            images=ns.images or None,
            expected_sha256=ns.expected_sha256,
            node_state_expected_sha256=ns.node_state_expected_sha256,
            images_expected_sha256=ns.images_expected_sha256,
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
    progress = None if ns.json else _ImportProgress()
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
            images=ns.images or None,
            expected_sha256=ns.expected_sha256,
            node_state_expected_sha256=ns.node_state_expected_sha256,
            images_expected_sha256=ns.images_expected_sha256,
            force=ns.force,
            progress=progress,
        )
    except (OSError, ValueError) as exc:
        detail = (
            format_runtime_storage_error(exc) if isinstance(exc, OSError) else str(exc)
        )
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
