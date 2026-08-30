"""Verified intake for existing EVE-NG and GNS3 lab archives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = 1
RECORD_KIND = "hybridops/lab-migration"
SUPPORTED_PLATFORMS = ("eve-ng", "gns3")
_MAX_DEFINITION_BYTES = 32 * 1024 * 1024
_MAX_MEMBERS = 200_000
_FREE_SPACE_RESERVE_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EVE_NODE_STATE_RE = re.compile(r"^[0-9]+/[^/]+/[0-9]+/[^/]+\.qcow2$")
_SSH_HOST_RE = re.compile(r"^[a-zA-Z0-9_.:-]+$")
_SSH_USER_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_filesystem_path(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _available_disk_bytes(path: Path) -> int:
    return shutil.disk_usage(_existing_filesystem_path(path)).free


def _require_disk_space(path: Path, payload_bytes: int, operation: str) -> None:
    filesystem_path = _existing_filesystem_path(path)
    available = shutil.disk_usage(filesystem_path).free
    required = int(payload_bytes) + _FREE_SPACE_RESERVE_BYTES
    if available < required:
        raise ValueError(
            f"insufficient disk space for {operation}: required {required} bytes, "
            f"available {available} bytes on the filesystem containing "
            f"{filesystem_path}"
        )


def _regular_file(raw: str | Path, field: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{field} is not a regular file: {path}")
    if Path(raw).expanduser().is_symlink():
        raise ValueError(f"{field} must not be a symbolic link: {raw}")
    return path


def _expected_checksum(value: str, field: str) -> str:
    checksum = str(value or "").strip().lower()
    if checksum and not _SHA256_RE.fullmatch(checksum):
        raise ValueError(f"{field} must contain 64 hexadecimal characters")
    return checksum


def _ssh_name(value: str, field: str) -> str:
    candidate = str(value or "").strip()
    pattern = _SSH_USER_RE if field == "user" else _SSH_HOST_RE
    if not candidate or candidate.startswith("-") or not pattern.fullmatch(candidate):
        raise ValueError(f"{field} is not a valid SSH name")
    return candidate


def _normalised_member_name(name: str) -> str:
    if "\\" in name:
        raise ValueError(f"archive member uses a non-portable path: {name}")
    if name.startswith("/"):
        raise ValueError(f"archive contains an absolute path: {name}")
    path = PurePosixPath(name)
    if ".." in path.parts:
        raise ValueError(f"archive member escapes its root: {name}")
    normalised = str(path)
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return "" if normalised == "." else normalised.rstrip("/")


def _safe_members(handle: tarfile.TarFile) -> list[tuple[tarfile.TarInfo, str]]:
    checked: list[tuple[tarfile.TarInfo, str]] = []
    seen: set[str] = set()
    for index, member in enumerate(handle, start=1):
        if index > _MAX_MEMBERS:
            raise ValueError(f"archive contains more than {_MAX_MEMBERS} members")
        name = _normalised_member_name(member.name)
        if member.issym() or member.islnk():
            raise ValueError(f"archive contains a link: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"archive contains an unsupported member: {member.name}")
        if member.isfile() and not name:
            raise ValueError("archive contains a file with an empty path")
        if name and name in seen:
            raise ValueError(f"archive contains a duplicate member: {name}")
        if name:
            seen.add(name)
        checked.append((member, name))
    if not checked:
        raise ValueError("archive is empty")
    return checked


def _read_definition(handle: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    if member.size > _MAX_DEFINITION_BYTES:
        raise ValueError(f"lab definition is too large to inspect: {member.name}")
    source = handle.extractfile(member)
    if source is None:
        raise ValueError(f"unable to read lab definition: {member.name}")
    with source:
        payload = source.read(_MAX_DEFINITION_BYTES + 1)
    if len(payload) > _MAX_DEFINITION_BYTES:
        raise ValueError(f"lab definition is too large to inspect: {member.name}")
    return payload


def _eve_image_references(
    handle: tarfile.TarFile,
    definitions: Iterable[tarfile.TarInfo],
) -> list[str]:
    references: set[str] = set()
    for member in definitions:
        try:
            root = ET.fromstring(_read_definition(handle, member))
        except ET.ParseError as exc:
            raise ValueError(f"invalid EVE-NG lab definition: {member.name}") from exc
        for element in root.iter():
            image = str(element.attrib.get("image") or "").strip()
            if image:
                references.add(image)
    return sorted(references)


def _walk_json_images(value: Any, *, key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk_json_images(child, key=str(child_key).lower())
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_json_images(child, key=key)
        return
    if isinstance(value, str) and ("image" in key or "disk" in key):
        candidate = value.strip()
        if candidate:
            yield candidate


def _gns3_image_references(
    handle: tarfile.TarFile,
    definitions: Iterable[tarfile.TarInfo],
) -> list[str]:
    references: set[str] = set()
    for member in definitions:
        try:
            payload = json.loads(_read_definition(handle, member))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"invalid GNS3 project definition: {member.name}") from exc
        references.update(_walk_json_images(payload))
    return sorted(references)


def _inspect_primary(path: Path, platform: str) -> dict[str, Any]:
    try:
        with tarfile.open(path, mode="r:*") as handle:
            members = _safe_members(handle)
            names = [name for _, name in members if name]
            files = [(member, name) for member, name in members if member.isfile()]
            if platform == "eve-ng":
                definitions = [
                    member for member, name in files if name.lower().endswith(".unl")
                ]
                if not definitions:
                    raise ValueError("EVE-NG archive contains no .unl lab definitions")
                if any(name.startswith("opt/unetlab/labs/") for name in names):
                    raise ValueError(
                        "EVE-NG archive must be relative to /opt/unetlab/labs"
                    )
                references = _eve_image_references(handle, definitions)
                return {
                    "definition_count": len(definitions),
                    "expanded_size_bytes": sum(member.size for member, _ in files),
                    "image_references": references,
                    "images_included": False,
                    "member_count": len(members),
                }

            allowed_roots = {
                "projects",
                "appliances",
                "symbols",
                "images",
            }
            outside = sorted(
                name
                for name in names
                if name.split("/", 1)[0] not in allowed_roots
                and name != ".config/GNS3"
                and not name.startswith(".config/GNS3/")
            )
            if outside:
                raise ValueError(
                    f"GNS3 archive contains an unsupported root: {outside[0]}"
                )
            definitions = [
                member
                for member, name in files
                if name.startswith("projects/") and name.lower().endswith(".gns3")
            ]
            if not definitions:
                raise ValueError("GNS3 archive contains no project definitions")
            references = _gns3_image_references(handle, definitions)
            return {
                "definition_count": len(definitions),
                "expanded_size_bytes": sum(member.size for member, _ in files),
                "image_references": references,
                "images_included": any(
                    name == "images" or name.startswith("images/") for name in names
                ),
                "member_count": len(members),
            }
    except tarfile.TarError as exc:
        raise ValueError(f"archive is not a readable tar archive: {path}") from exc


def _inspect_eve_node_state(path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(path, mode="r:*") as handle:
            members = _safe_members(handle)
            files = [name for member, name in members if member.isfile()]
            if not files:
                raise ValueError("EVE-NG node-state archive contains no files")
            invalid = [name for name in files if not _EVE_NODE_STATE_RE.fullmatch(name)]
            if invalid:
                raise ValueError(
                    f"EVE-NG node-state member has an invalid path: {invalid[0]}"
                )
            return {
                "expanded_size_bytes": sum(
                    member.size for member, _ in members if member.isfile()
                ),
                "member_count": len(members),
                "overlay_count": len(files),
            }
    except tarfile.TarError as exc:
        raise ValueError(
            f"node-state archive is not a readable tar archive: {path}"
        ) from exc


def inspect_migration_archive(
    *,
    platform: str,
    archive: str | Path,
    node_state: str | Path | None = None,
    expected_sha256: str = "",
    node_state_expected_sha256: str = "",
) -> dict[str, Any]:
    platform_name = str(platform or "").strip().lower()
    if platform_name not in SUPPORTED_PLATFORMS:
        raise ValueError(
            "platform must be one of: " + ", ".join(SUPPORTED_PLATFORMS)
        )

    archive_path = _regular_file(archive, "archive")
    archive_checksum = _sha256(archive_path)
    expected = _expected_checksum(expected_sha256, "expected SHA-256")
    if expected and archive_checksum != expected:
        raise ValueError("archive SHA-256 checksum does not match")

    primary = _inspect_primary(archive_path, platform_name)
    node_report: dict[str, Any] | None = None
    node_path: Path | None = None
    if node_state:
        if platform_name != "eve-ng":
            raise ValueError("a separate node-state archive is only valid for EVE-NG")
        node_path = _regular_file(node_state, "node-state archive")
        node_checksum = _sha256(node_path)
        node_expected = _expected_checksum(
            node_state_expected_sha256,
            "node-state expected SHA-256",
        )
        if node_expected and node_checksum != node_expected:
            raise ValueError("node-state archive SHA-256 checksum does not match")
        node_report = {
            "path": str(node_path),
            "size_bytes": node_path.stat().st_size,
            "sha256": node_checksum,
            **_inspect_eve_node_state(node_path),
        }
    elif node_state_expected_sha256:
        raise ValueError("node-state expected SHA-256 requires --node-state")

    warnings: list[str] = []
    if primary["image_references"] and not primary["images_included"]:
        warnings.append("referenced base images must be available on the target")
    if platform_name == "eve-ng" and node_report is None:
        warnings.append("writable QEMU node state is not included")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "hybridops/lab-migration-inspection",
        "status": "compatible",
        "platform": platform_name,
        "archive": {
            "path": str(archive_path),
            "size_bytes": archive_path.stat().st_size,
            "expanded_size_bytes": primary["expanded_size_bytes"],
            "sha256": archive_checksum,
            "member_count": primary["member_count"],
        },
        "definition_count": primary["definition_count"],
        "image_references": primary["image_references"],
        "images_included": primary["images_included"],
        "node_state": node_report,
        "warnings": warnings,
    }


def _remote_capture_script(
    platform: str,
    *,
    node_state: bool = False,
    include_images: bool = False,
    output_available_bytes: int,
) -> str:
    usable_bytes = max(0, output_available_bytes - _FREE_SPACE_RESERVE_BYTES)
    capacity_check = f"""available={output_available_bytes}
capacity={usable_bytes}
if [ "$required" -gt "$capacity" ]; then
  echo "Insufficient disk space for lab capture: source requires at least $required bytes; output filesystem has $available bytes available" >&2
  exit 23
fi
"""
    if platform == "eve-ng":
        if node_state:
            return f"""set -eu
root=/opt/unetlab/tmp
test -d "$root" || {{ echo 'EVE-NG node-state root not found' >&2; exit 20; }}
if pgrep -af '[/]opt/qemu[^ ]*/bin/qemu-system-' >/dev/null; then
  echo 'EVE-NG QEMU nodes are running; stop them before capture' >&2
  exit 21
fi
cd "$root"
find . -type f -name '*.qcow2' -printf '%P\\n' -quit | grep -q . || {{
  echo 'No EVE-NG QEMU node state was found' >&2
  exit 22
}}
required=$(find . -type f -name '*.qcow2' -printf '%b\\n' | awk '{{total += $1}} END {{printf "%.0f\\n", total * 512}}')
{capacity_check}find . -type f -name '*.qcow2' -printf '%P\\0' | sort -z | \
  tar --null --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  -czf - --files-from=-
"""
        return f"""set -eu
root=/opt/unetlab/labs
test -d "$root" || {{ echo 'EVE-NG labs root not found' >&2; exit 20; }}
if pgrep -af '[/]opt/qemu[^ ]*/bin/qemu-system-' >/dev/null; then
  echo 'EVE-NG QEMU nodes are running; stop them before capture' >&2
  exit 21
fi
find "$root" -type f -name '*.unl' -print -quit | grep -q . || {{
  echo 'No EVE-NG lab definitions were found' >&2
  exit 22
}}
required=$(find "$root" -type f -printf '%b\\n' | awk '{{total += $1}} END {{printf "%.0f\\n", total * 512}}')
{capacity_check}exec tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  -czf - -C "$root" .
"""

    image_member = " images" if include_images else ""
    return f"""set -eu
root=/var/lib/gns3
test -d "$root/projects" || {{ echo 'GNS3 projects root not found' >&2; exit 20; }}
if pgrep -af '[g]ns3server' >/dev/null; then
  echo 'GNS3 is running; stop it before capture' >&2
  exit 21
fi
cd "$root"
set -- projects
for member in appliances symbols .config/GNS3{image_member}; do
  test -e "$root/$member" && set -- "$@" "$member"
done
required=$(du -s --block-size=1 "$@" | awk '{{total += $1}} END {{printf "%.0f\\n", total}}')
{capacity_check}exec tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  -czf - -C "$root" "$@"
"""


def _ssh_capture_argv(
    *,
    host: str,
    user: str,
    port: int,
    identity_file: str | Path | None,
    become: bool,
    script: str,
) -> list[str]:
    host_name = _ssh_name(host, "host")
    user_name = _ssh_name(user, "user") if user else ""
    if not 1 <= int(port) <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    target = f"{user_name}@{host_name}" if user_name else host_name
    argv = ["ssh", "-T", "-p", str(port)]
    if identity_file:
        identity = _regular_file(identity_file, "identity file")
        argv.extend(["-i", str(identity)])
    remote = ["sudo", "-n", "sh", "-c", script] if become else ["sh", "-c", script]
    return [*argv, target, shlex.join(remote)]


def _capture_stream(argv: list[str], candidate: Path) -> None:
    try:
        with candidate.open("wb") as output:
            result = subprocess.run(
                argv,
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
            output.flush()
            os.fsync(output.fileno())
    except FileNotFoundError as exc:
        raise ValueError("ssh is not installed or is not available on PATH") from exc
    if result.returncode == 0:
        os.chmod(candidate, 0o600)
        return
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    lowered_detail = detail.lower()
    if "no space left on device" in lowered_detail or "disk quota exceeded" in lowered_detail:
        raise ValueError(
            "insufficient disk space for lab capture: the output filesystem "
            "became full while writing the archive"
        )
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    concise = "; ".join(lines[-3:])[-800:] or f"ssh exited with status {result.returncode}"
    raise ValueError(f"source capture failed: {concise}")


def _capture_destination(raw: str | Path, field: str) -> Path:
    expanded = Path(raw).expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{field} must not be a symbolic link: {expanded}")
    return expanded.parent.resolve() / expanded.name


def _capture_candidate(path: Path, force: bool) -> Path:
    if path.exists():
        if not path.is_file():
            raise ValueError(f"output is not a regular file: {path}")
        if not force:
            raise ValueError(f"output already exists: {path}; use --force to replace it")
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        os.chmod(path.parent, 0o700)
    fd, candidate_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".candidate",
        dir=str(path.parent),
    )
    os.close(fd)
    candidate = Path(candidate_name)
    os.chmod(candidate, 0o600)
    return candidate


def _default_node_state_output(primary: Path) -> Path:
    name = primary.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.lower().endswith(suffix):
            return primary.with_name(name[: -len(suffix)] + ".node-state.tar.gz")
    return primary.with_name(name + ".node-state.tar.gz")


def capture_existing_lab(
    *,
    platform: str,
    host: str,
    output: str | Path,
    user: str = "",
    port: int = 22,
    identity_file: str | Path | None = None,
    become: bool = False,
    include_node_state: bool = False,
    node_state_output: str | Path | None = None,
    include_images: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    platform_name = str(platform or "").strip().lower()
    if platform_name not in SUPPORTED_PLATFORMS:
        raise ValueError(
            "platform must be one of: " + ", ".join(SUPPORTED_PLATFORMS)
        )
    if include_node_state and platform_name != "eve-ng":
        raise ValueError("separate node-state capture is only valid for EVE-NG")
    if include_images and platform_name != "gns3":
        raise ValueError("--include-images is only valid for GNS3")
    if node_state_output and not include_node_state:
        raise ValueError("--node-state-output requires --include-node-state")

    destination = _capture_destination(output, "output")
    node_destination: Path | None = None
    if include_node_state:
        node_destination = (
            _capture_destination(node_state_output, "node-state output")
            if node_state_output
            else _default_node_state_output(destination)
        )
        if node_destination == destination:
            raise ValueError("node-state output must differ from the primary output")

    primary_candidate: Path | None = None
    node_candidate: Path | None = None
    try:
        primary_candidate = _capture_candidate(destination, force)
        if node_destination is not None:
            node_candidate = _capture_candidate(node_destination, force)
        primary_argv = _ssh_capture_argv(
            host=host,
            user=user,
            port=port,
            identity_file=identity_file,
            become=become,
            script=_remote_capture_script(
                platform_name,
                include_images=include_images,
                output_available_bytes=_available_disk_bytes(destination.parent),
            ),
        )
        _capture_stream(primary_argv, primary_candidate)
        if node_candidate is not None:
            node_argv = _ssh_capture_argv(
                host=host,
                user=user,
                port=port,
                identity_file=identity_file,
                become=become,
                script=_remote_capture_script(
                    platform_name,
                    node_state=True,
                    output_available_bytes=_available_disk_bytes(
                        node_destination.parent
                    ),
                ),
            )
            _capture_stream(node_argv, node_candidate)

        report = inspect_migration_archive(
            platform=platform_name,
            archive=primary_candidate,
            node_state=node_candidate,
        )
        os.replace(primary_candidate, destination)
        if node_candidate is not None and node_destination is not None:
            os.replace(node_candidate, node_destination)
        report["archive"]["path"] = str(destination)
        if isinstance(report.get("node_state"), dict) and node_destination is not None:
            report["node_state"]["path"] = str(node_destination)
        report["source"] = {"host": host, "user": user or None}
        return report
    finally:
        if primary_candidate is not None:
            primary_candidate.unlink(missing_ok=True)
        if node_candidate is not None:
            node_candidate.unlink(missing_ok=True)


def platform_for_blueprint(payload: dict[str, Any]) -> str:
    lifecycle = payload.get("archive_before_destroy")
    if not isinstance(lifecycle, dict) or not lifecycle:
        raise ValueError("target blueprint does not declare a lab archive lifecycle")
    module_ref = str(lifecycle.get("module_ref") or "").strip()
    prefix = str(lifecycle.get("contract_prefix") or "").strip()
    if module_ref.endswith("/eve-ng-lab-archive") or prefix.startswith("eveng_"):
        return "eve-ng"
    if module_ref.endswith("/gns3-lab-archive") or prefix.startswith("gns3_"):
        return "gns3"
    raise ValueError("target blueprint does not support lab migration intake")


def _record_slug(blueprint_ref: str) -> str:
    reference = str(blueprint_ref or "").strip()
    if not reference:
        raise ValueError("target blueprint has no blueprint_ref")
    readable = re.sub(r"[^a-zA-Z0-9_.-]+", "_", reference).strip("_")
    suffix = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:8]
    return f"{readable}-{suffix}"


def migration_record_path(paths, blueprint_ref: str) -> Path:
    return paths.state_dir / "lab-migrations" / f"{_record_slug(blueprint_ref)}.json"


def _copy_verified(source: Path, destination: Path, checksum: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    if destination.is_symlink():
        raise ValueError(f"staged archive must not be a symbolic link: {destination}")
    if destination.exists() and not destination.is_file():
        raise ValueError(f"staged archive is not a regular file: {destination}")
    if destination.is_file() and _sha256(destination) == checksum:
        os.chmod(destination, 0o600)
        return
    fd, candidate_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".candidate",
        dir=str(destination.parent),
    )
    candidate = Path(candidate_name)
    try:
        with os.fdopen(fd, "wb") as target_handle, source.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        os.chmod(candidate, 0o600)
        if _sha256(candidate) != checksum:
            raise ValueError(f"staged archive checksum verification failed: {source}")
        os.replace(candidate, destination)
    finally:
        candidate.unlink(missing_ok=True)


def _write_record(path: Path, record: dict[str, Any]) -> None:
    from hyops.runtime.state import write_json_atomic

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    write_json_atomic(path, record, mode=0o600)


def _bundle_id(primary_checksum: str, node_checksum: str) -> str:
    identity = f"{primary_checksum}:{node_checksum}".encode("ascii")
    return hashlib.sha256(identity).hexdigest()[:16]


def stage_migration_archive(
    *,
    paths,
    payload: dict[str, Any],
    platform: str,
    archive: str | Path,
    node_state: str | Path | None = None,
    expected_sha256: str = "",
    node_state_expected_sha256: str = "",
    force: bool = False,
) -> dict[str, Any]:
    platform_name = str(platform or "").strip().lower()
    target_platform = platform_for_blueprint(payload)
    if platform_name != target_platform:
        raise ValueError(
            f"source platform {platform_name} does not match target blueprint platform "
            f"{target_platform}"
        )
    inspection = inspect_migration_archive(
        platform=platform_name,
        archive=archive,
        node_state=node_state,
        expected_sha256=expected_sha256,
        node_state_expected_sha256=node_state_expected_sha256,
    )

    blueprint_ref = str(payload.get("blueprint_ref") or "").strip()
    record_path = migration_record_path(paths, blueprint_ref)
    existing: dict[str, Any] | None = None
    if record_path.is_file():
        try:
            loaded = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"migration record is unreadable: {record_path}") from exc
        if isinstance(loaded, dict):
            existing = loaded
    existing_archive = (existing or {}).get("archive")
    existing_checksum = (
        str(existing_archive.get("sha256") or "")
        if isinstance(existing_archive, dict)
        else ""
    )
    node_inspection = inspection.get("node_state")
    node_checksum = str(node_inspection.get("sha256") or "") if node_inspection else ""
    existing_node = (existing or {}).get("node_state")
    existing_node_checksum = (
        str(existing_node.get("sha256") or "") if isinstance(existing_node, dict) else ""
    )
    if existing and (existing_checksum, existing_node_checksum) != (
        inspection["archive"]["sha256"],
        node_checksum,
    ) and not force:
        raise ValueError(
            "a different migration bundle is already staged for this blueprint; "
            "use --force to replace the active record"
        )

    bundle_id = _bundle_id(inspection["archive"]["sha256"], node_checksum)
    destination_root = (
        paths.root / "artifacts" / "lab-migrations" / _record_slug(blueprint_ref) / bundle_id
    )
    archive_destination = destination_root / "labs.tar.gz"
    copy_bytes = 0
    if not (
        archive_destination.is_file()
        and _sha256(archive_destination) == inspection["archive"]["sha256"]
    ):
        copy_bytes += int(inspection["archive"]["size_bytes"])
    if node_inspection:
        node_destination = destination_root / "labs.node-state.tar.gz"
        if not (
            node_destination.is_file()
            and _sha256(node_destination) == node_inspection["sha256"]
        ):
            copy_bytes += int(node_inspection["size_bytes"])
    if copy_bytes:
        _require_disk_space(destination_root, copy_bytes, "migration import")

    _copy_verified(
        Path(inspection["archive"]["path"]),
        archive_destination,
        inspection["archive"]["sha256"],
    )

    staged_node: dict[str, Any] | None = None
    if node_inspection:
        _copy_verified(
            Path(node_inspection["path"]),
            node_destination,
            node_inspection["sha256"],
        )
        staged_node = {
            key: value for key, value in node_inspection.items() if key != "path"
        }
        staged_node["path"] = str(node_destination)

    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": RECORD_KIND,
        "status": "verified",
        "imported_at": _utc_now(),
        "platform": platform_name,
        "blueprint_ref": blueprint_ref,
        "archive": {
            key: value for key, value in inspection["archive"].items() if key != "path"
        },
        "node_state": staged_node,
        "definition_count": inspection["definition_count"],
        "image_references": inspection["image_references"],
        "images_included": inspection["images_included"],
        "warnings": inspection["warnings"],
    }
    record["archive"]["path"] = str(archive_destination)
    if existing and (existing_checksum, existing_node_checksum) != (
        record["archive"]["sha256"],
        node_checksum,
    ):
        record["supersedes"] = {
            "archive_sha256": existing_checksum,
            "node_state_sha256": existing_node_checksum,
            "imported_at": str(existing.get("imported_at") or ""),
        }
    _write_record(record_path, record)
    return record


def _verified_staged_file(
    *,
    paths,
    value: Any,
    checksum: Any,
    field: str,
) -> tuple[Path, str]:
    path = Path(str(value or "")).expanduser().resolve()
    allowed = (paths.root / "artifacts" / "lab-migrations").resolve()
    try:
        path.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"{field} is outside the migration artifact root") from exc
    expected = str(checksum or "").strip().lower()
    if not path.is_file() or not _SHA256_RE.fullmatch(expected):
        raise ValueError(f"{field} is missing or unverifiable")
    if _sha256(path) != expected:
        raise ValueError(f"{field} checksum verification failed: {path}")
    return path, expected


def load_migration_archive(
    *,
    paths,
    payload: dict[str, Any],
) -> tuple[Path, str, Path | None, str] | None:
    blueprint_ref = str(payload.get("blueprint_ref") or "").strip()
    path = migration_record_path(paths, blueprint_ref)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"migration record is unreadable: {path}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"migration record is invalid: {path}")
    if record.get("schema_version") != SCHEMA_VERSION or record.get("kind") != RECORD_KIND:
        raise ValueError(f"migration record has an unsupported schema: {path}")
    if record.get("status") != "verified":
        raise ValueError(f"migration record is not verified: {path}")
    if str(record.get("blueprint_ref") or "") != blueprint_ref:
        raise ValueError(f"migration record blueprint does not match {blueprint_ref}")
    platform = str(record.get("platform") or "")
    if platform != platform_for_blueprint(payload):
        raise ValueError("migration record platform does not match the target blueprint")

    archive_data = record.get("archive")
    if not isinstance(archive_data, dict):
        raise ValueError(f"migration record has no archive: {path}")
    archive_path, checksum = _verified_staged_file(
        paths=paths,
        value=archive_data.get("path"),
        checksum=archive_data.get("sha256"),
        field="migration archive",
    )

    node_path: Path | None = None
    node_checksum = ""
    node_data = record.get("node_state")
    if node_data is not None:
        if platform != "eve-ng":
            raise ValueError(f"migration node-state record is invalid: {path}")
        if not isinstance(node_data, dict):
            raise ValueError(f"migration node-state record is invalid: {path}")
        node_path, node_checksum = _verified_staged_file(
            paths=paths,
            value=node_data.get("path"),
            checksum=node_data.get("sha256"),
            field="migration node-state archive",
        )
    return archive_path, checksum, node_path, node_checksum
