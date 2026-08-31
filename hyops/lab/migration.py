"""Verified intake for existing network-lab archives."""

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
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 1
RECORD_KIND = "hybridops/lab-migration"
SUPPORTED_PLATFORMS = ("eve-ng", "gns3", "containerlab")
CaptureProgress = Callable[[dict[str, Any]], None]
_MAX_DEFINITION_BYTES = 32 * 1024 * 1024
_MAX_MEMBERS = 200_000
_FREE_SPACE_RESERVE_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EVE_NODE_STATE_RE = re.compile(r"^[0-9]+/[^/]+/[0-9]+/[^/]+\.qcow2$")
_SSH_HOST_RE = re.compile(r"^[a-zA-Z0-9_.:-]+$")
_SSH_USER_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_EVE_IMAGE_CAPTURE_PROGRAM = r"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

mode = sys.argv[1]
labs_root = Path(sys.argv[2])
addons_root = Path(sys.argv[3])


def fail(message, status=24):
    print(message, file=sys.stderr)
    raise SystemExit(status)


def safe_reference(value):
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        fail(f"EVE-NG lab contains an unsafe image reference: {value!r}")
    return value


requirements = set()
labs_resolved = labs_root.resolve()
for definition in sorted(labs_root.rglob("*.unl")):
    if definition.is_symlink():
        fail(f"EVE-NG lab definition must not be a symbolic link: {definition}")
    try:
        definition.resolve(strict=True).relative_to(labs_resolved)
    except (FileNotFoundError, ValueError):
        fail(f"EVE-NG lab definition has an unsafe path: {definition}")
    if definition.stat().st_size > 32 * 1024 * 1024:
        fail(f"EVE-NG lab definition exceeds the 32 MiB limit: {definition}")
    payload = definition.read_bytes()
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, flags=re.IGNORECASE):
        fail(f"EVE-NG lab definition contains a DTD or entity declaration: {definition}")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        fail(f"Invalid EVE-NG lab definition: {definition}")
    for element in root.iter():
        image = safe_reference(str(element.attrib.get("image") or "").strip()) if element.attrib.get("image") else ""
        if not image:
            continue
        node_type = str(element.attrib.get("type") or "").strip().lower()
        if node_type == "qemu":
            candidates = [Path("qemu") / image]
        elif node_type.startswith("iol"):
            candidates = [Path("iol/bin") / image]
        elif node_type == "dynamips":
            candidates = [Path("dynamips") / image]
        else:
            candidates = [
                Path("qemu") / image,
                Path("iol/bin") / image,
                Path("dynamips") / image,
            ]
        matches = [candidate for candidate in candidates if (addons_root / candidate).exists()]
        if not matches:
            fail(f"Referenced EVE-NG base image was not found: {image}", 22)
        requirements.update(matches)

if not requirements:
    fail("No referenced EVE-NG base images were found", 22)

addons_resolved = addons_root.resolve()
selected = []
seen_inodes = set()
allocated_bytes = 0
for relative in sorted(requirements, key=lambda item: item.as_posix()):
    source = addons_root / relative
    try:
        source.resolve(strict=True).relative_to(addons_resolved)
    except (FileNotFoundError, ValueError):
        fail(f"Referenced EVE-NG base image has an unsafe path: {relative}")
    paths = [source]
    if source.is_dir():
        paths.extend(sorted(source.rglob("*")))
    for path in paths:
        if path.is_symlink():
            fail(f"Referenced EVE-NG base image contains a symbolic link: {path}")
        stat = path.stat()
        inode = (stat.st_dev, stat.st_ino)
        if inode in seen_inodes:
            continue
        seen_inodes.add(inode)
        allocated_bytes += stat.st_blocks * 512
    selected.append(relative.as_posix())

if mode == "assess":
    print(allocated_bytes)
    raise SystemExit(0)
if mode != "capture":
    fail("Unsupported EVE-NG image capture mode")

compressor = "pigz -1" if shutil.which("pigz") else "gzip -1"
command = [
    "tar",
    "--sort=name",
    "--mtime=@0",
    "--owner=0",
    "--group=0",
    "--numeric-owner",
    "--sparse",
    "--null",
    "--verbatim-files-from",
    "-I",
    compressor,
    "-cf",
    "-",
    "-C",
    str(addons_root),
    "--files-from=-",
]
file_list = b"".join(os.fsencode(path) + b"\0" for path in selected)
result = subprocess.run(command, input=file_list, stdout=sys.stdout.buffer, check=False)
raise SystemExit(result.returncode)
"""

_CONTAINERLAB_CAPTURE_PROGRAM = r"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile

mode = sys.argv[1]
source_root = Path(sys.argv[2])
topology_relpath = sys.argv[3]
source_labdir_base = sys.argv[4]
target_labdir_base = sys.argv[5]


def fail(message, status=24):
    print(message, file=sys.stderr)
    raise SystemExit(status)


def safe_relative(value):
    if (
        not value
        or value in {".", ".."}
        or value.startswith("/")
        or "\\" in value
        or ".." in PurePosixPath(value).parts
        or any(ord(character) < 32 for character in value)
    ):
        fail(f"Containerlab topology path is unsafe: {value!r}")
    return PurePosixPath(value).as_posix()


def source_files(root):
    resolved = root.resolve(strict=True)
    selected = []
    for current, directories, files in os.walk(resolved, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(resolved)
        kept_directories = []
        for name in sorted(directories):
            path = current_path / name
            relative = relative_current / name
            if len(relative.parts) == 1 and name.startswith("clab-"):
                continue
            if path.is_symlink():
                fail(f"Containerlab source contains a symbolic link: {relative}")
            if not path.is_dir():
                fail(f"Containerlab source contains an unsupported entry: {relative}")
            kept_directories.append(name)
        directories[:] = kept_directories
        for name in sorted(files):
            path = current_path / name
            relative = relative_current / name
            if path.is_symlink():
                fail(f"Containerlab source contains a symbolic link: {relative}")
            file_stat = path.stat()
            if not stat.S_ISREG(file_stat.st_mode):
                fail(f"Containerlab source contains an unsupported entry: {relative}")
            selected.append((path, PurePosixPath(relative.as_posix()), file_stat))
    return selected


def image_references(topology, inspection):
    references = set()
    try:
        text = topology.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    for match in re.finditer(r"(?m)^\s*image:\s*[\"']?([^#\"'\s]+)", text):
        references.add(match.group(1).strip())

    def walk(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key).lower())
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and "image" in key and value.strip():
            references.add(value.strip())

    if inspection:
        try:
            walk(json.loads(inspection))
        except (json.JSONDecodeError, RecursionError):
            pass
    return sorted(references)


def add_bytes(handle, name, payload, file_mode=0o640):
    member = tarfile.TarInfo(name=name)
    member.size = len(payload)
    member.mode = file_mode
    member.uid = 0
    member.gid = 0
    member.uname = "root"
    member.gname = "root"
    member.mtime = 0
    handle.addfile(member, io.BytesIO(payload))


def add_directory(handle, name, directory_mode=0o750):
    member = tarfile.TarInfo(name=name.rstrip("/") + "/")
    member.type = tarfile.DIRTYPE
    member.mode = directory_mode
    member.uid = 0
    member.gid = 0
    member.uname = "root"
    member.gname = "root"
    member.mtime = 0
    handle.addfile(member)


def add_file(handle, source, name, file_stat):
    member = tarfile.TarInfo(name=name)
    member.size = file_stat.st_size
    member.mode = stat.S_IMODE(file_stat.st_mode) & 0o777
    member.uid = 0
    member.gid = 0
    member.uname = "root"
    member.gname = "root"
    member.mtime = 0
    with source.open("rb") as source_handle:
        handle.addfile(member, source_handle)


topology_relpath = safe_relative(topology_relpath)
try:
    source_resolved = source_root.resolve(strict=True)
except FileNotFoundError:
    fail(f"Containerlab source root was not found: {source_root}", 20)
if not source_resolved.is_dir():
    fail(f"Containerlab source root is not a directory: {source_root}", 20)
if source_resolved in {Path("/"), Path("/var/lib/docker")}:
    fail(f"Containerlab source root is too broad: {source_resolved}")
for label, value in (
    ("source", source_labdir_base),
    ("target", target_labdir_base),
):
    if not value and label == "source":
        continue
    if (
        not value.startswith("/")
        or "\\" in value
        or ".." in PurePosixPath(value).parts
        or any(ord(character) < 32 for character in value)
    ):
        fail(f"Containerlab {label} labdir base is invalid: {value!r}")

topology = source_resolved / topology_relpath
try:
    topology.resolve(strict=True).relative_to(source_resolved)
except (FileNotFoundError, ValueError):
    fail(f"Containerlab topology was not found under the source root: {topology_relpath}", 20)
if topology.is_symlink() or not topology.is_file():
    fail(f"Containerlab topology is not a regular file: {topology_relpath}", 20)

files = source_files(source_resolved)
if mode == "assess":
    allocated = sum(item[2].st_blocks * 512 for item in files)
    print(allocated)
    raise SystemExit(0)
if mode != "capture":
    fail("Unsupported Containerlab capture mode")

version_payload = ""
inspection_payload = ""
save_rc = 127
with tempfile.TemporaryDirectory(prefix="hyops-containerlab-") as temporary:
    saved_configs = Path(temporary) / "startup-configs"
    saved_configs.mkdir(mode=0o750)
    containerlab_environment = {
        **os.environ,
        "CLAB_VERSION_CHECK": "disable",
    }
    if source_labdir_base:
        containerlab_environment["CLAB_LABDIR_BASE"] = source_labdir_base
    try:
        saved = subprocess.run(
            [
                "containerlab",
                "save",
                "-t",
                str(topology),
                "--copy",
                str(saved_configs),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=containerlab_environment,
            timeout=300,
        )
        save_rc = saved.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired):
        save_rc = 127

    try:
        version = subprocess.run(
            ["containerlab", "version", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=15,
        )
        if version.returncode == 0:
            version_payload = version.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        inspection = subprocess.run(
            ["containerlab", "inspect", "-t", str(topology), "-f", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=containerlab_environment,
            text=True,
            timeout=60,
        )
        if inspection.returncode == 0:
            inspection_payload = inspection.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    topology_sha256 = hashlib.sha256(topology.read_bytes()).hexdigest()
    try:
        version_value = json.loads(version_payload).get("version", "") if version_payload else ""
    except (AttributeError, json.JSONDecodeError):
        version_value = ""
    manifest = {
        "schema": "hybridops.containerlab.recovery/v1",
        "mode": "rebuild",
        "topology_relpath": topology_relpath,
        "topology_sha256": topology_sha256,
        "source_root_included": True,
        "containerlab_version": str(version_value),
        "image_refs": image_references(topology, inspection_payload),
        "labdir_base": target_labdir_base,
        "native_config_save_attempted": True,
        "native_config_save_rc": save_rc,
        "native_snapshots_requested": False,
        "lab_directory_included": False,
        "additional_paths_count": 0,
    }

    bundle = "containerlab-migration"
    source_prefix = f"{bundle}/lab-source"
    saved_files = source_files(saved_configs)
    archive_files = {
        relative.as_posix(): (source, relative, file_stat)
        for source, relative, file_stat in files
    }
    if save_rc == 0:
        for source, relative, file_stat in saved_files:
            archive_relative = PurePosixPath("startup-configs") / relative
            archive_files[archive_relative.as_posix()] = (
                source,
                archive_relative,
                file_stat,
            )
    with tarfile.open(
        fileobj=sys.stdout.buffer,
        mode="w|gz",
        compresslevel=1,
        format=tarfile.PAX_FORMAT,
    ) as archive:
        add_directory(archive, bundle)
        add_directory(archive, source_prefix)
        directories = set()
        for _, relative, _ in archive_files.values():
            for parent in relative.parents:
                if str(parent) not in {"", "."}:
                    directories.add(parent.as_posix())
        for directory in sorted(directories, key=lambda item: (item.count("/"), item)):
            add_directory(archive, f"{source_prefix}/{directory}")
        for source, relative, file_stat in sorted(
            archive_files.values(),
            key=lambda item: item[1].as_posix(),
        ):
            add_file(
                archive,
                source,
                f"{source_prefix}/{relative.as_posix()}",
                file_stat,
            )
        add_bytes(
            archive,
            f"{bundle}/hybridops-recovery-manifest.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        if version_payload:
            add_bytes(
                archive,
                f"{bundle}/containerlab-version.json",
                (version_payload + "\n").encode("utf-8"),
            )
        if inspection_payload:
            add_bytes(
                archive,
                f"{bundle}/containerlab-inspect.json",
                (inspection_payload + "\n").encode("utf-8"),
            )
"""


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


def _format_bytes(value: int) -> str:
    size = max(0, int(value))
    for unit, divisor in (
        ("TiB", 1024**4),
        ("GiB", 1024**3),
        ("MiB", 1024**2),
        ("KiB", 1024),
    ):
        if size >= divisor:
            return f"{size / divisor:.1f} {unit} ({size} bytes)"
    return f"{size} bytes"


def _require_disk_space(path: Path, payload_bytes: int, operation: str) -> None:
    filesystem_path = _existing_filesystem_path(path)
    available = shutil.disk_usage(filesystem_path).free
    required = int(payload_bytes) + _FREE_SPACE_RESERVE_BYTES
    if available < required:
        raise ValueError(
            f"insufficient disk space for {operation}: "
            f"required {_format_bytes(required)}, "
            f"available {_format_bytes(available)} on the filesystem containing "
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
) -> tuple[list[str], list[tuple[str, str]]]:
    references: set[str] = set()
    requirements: set[tuple[str, str]] = set()
    for member in definitions:
        definition = _read_definition(handle, member)
        if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", definition, flags=re.IGNORECASE):
            raise ValueError(
                f"EVE-NG lab definition contains a DTD or entity declaration: {member.name}"
            )
        try:
            root = ET.fromstring(definition)
        except ET.ParseError as exc:
            raise ValueError(f"invalid EVE-NG lab definition: {member.name}") from exc
        for element in root.iter():
            image = str(element.attrib.get("image") or "").strip()
            if image:
                if (
                    image in {".", ".."}
                    or PurePosixPath(image).name != image
                    or "\\" in image
                    or any(ord(character) < 32 for character in image)
                ):
                    raise ValueError(
                        f"EVE-NG lab contains an unsafe image reference: {image}"
                    )
                references.add(image)
                node_type = str(element.attrib.get("type") or "").strip().lower()
                if node_type == "qemu":
                    requirements.add(("qemu", image))
                elif node_type.startswith("iol"):
                    requirements.add(("iol/bin", image))
                elif node_type == "dynamips":
                    requirements.add(("dynamips", image))
                else:
                    requirements.add(("*", image))
    return sorted(references), sorted(requirements)


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


def _inspect_containerlab_archive(
    handle: tarfile.TarFile,
    members: list[tuple[tarfile.TarInfo, str]],
) -> dict[str, Any]:
    named_members = {name: member for member, name in members if name}
    roots = {
        PurePosixPath(name).parts[0]
        for name in named_members
        if PurePosixPath(name).parts
    }
    if len(roots) != 1:
        raise ValueError("Containerlab archive must contain one recovery bundle root")
    bundle_root = next(iter(roots))
    manifest_name = f"{bundle_root}/hybridops-recovery-manifest.json"
    manifest_member = named_members.get(manifest_name)
    if manifest_member is None or not manifest_member.isfile():
        raise ValueError("Containerlab archive has no recovery manifest")
    try:
        manifest = json.loads(_read_definition(handle, manifest_member))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Containerlab recovery manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Containerlab recovery manifest is invalid")
    if manifest.get("schema") != "hybridops.containerlab.recovery/v1":
        raise ValueError("Containerlab recovery manifest schema is unsupported")
    if manifest.get("mode") not in {"ephemeral", "rebuild", "snapshot"}:
        raise ValueError("Containerlab recovery mode is unsupported")

    topology_relpath = str(manifest.get("topology_relpath") or "").strip()
    if (
        not topology_relpath
        or topology_relpath.startswith("/")
        or "\\" in topology_relpath
        or ".." in PurePosixPath(topology_relpath).parts
        or any(ord(character) < 32 for character in topology_relpath)
    ):
        raise ValueError("Containerlab recovery topology path is unsafe")
    topology_relpath = PurePosixPath(topology_relpath).as_posix()

    source_root_included = manifest.get("source_root_included")
    if not isinstance(source_root_included, bool):
        raise ValueError("Containerlab recovery source-root flag is invalid")
    source_prefix = f"{bundle_root}/lab-source" if source_root_included else bundle_root
    topology_name = f"{source_prefix}/{topology_relpath}"
    topology_member = named_members.get(topology_name)
    if topology_member is None or not topology_member.isfile():
        raise ValueError("Containerlab recovery topology is missing")
    topology_sha256 = str(manifest.get("topology_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(topology_sha256):
        raise ValueError("Containerlab recovery topology checksum is invalid")
    topology_payload = _read_definition(handle, topology_member)
    if hashlib.sha256(topology_payload).hexdigest() != topology_sha256:
        raise ValueError("Containerlab recovery topology checksum does not match")

    labdir_base = str(manifest.get("labdir_base") or "").strip()
    if (
        not labdir_base.startswith("/")
        or "\\" in labdir_base
        or ".." in PurePosixPath(labdir_base).parts
        or any(ord(character) < 32 for character in labdir_base)
    ):
        raise ValueError("Containerlab recovery labdir base is invalid")
    image_refs = manifest.get("image_refs")
    if not isinstance(image_refs, list) or len(image_refs) > 10_000:
        raise ValueError("Containerlab recovery image references are invalid")
    references: list[str] = []
    for value in image_refs:
        reference = str(value or "").strip() if isinstance(value, str) else ""
        if (
            not reference
            or len(reference) > 1024
            or any(ord(character) < 32 for character in reference)
        ):
            raise ValueError("Containerlab recovery image reference is invalid")
        references.append(reference)
    native_config_save_attempted = manifest.get("native_config_save_attempted", False)
    if not isinstance(native_config_save_attempted, bool):
        raise ValueError("Containerlab native configuration-save flag is invalid")
    native_config_save_rc = manifest.get("native_config_save_rc")
    if native_config_save_rc is not None and (
        isinstance(native_config_save_rc, bool)
        or not isinstance(native_config_save_rc, int)
    ):
        raise ValueError("Containerlab native configuration-save result is invalid")
    if native_config_save_attempted != (native_config_save_rc is not None):
        raise ValueError("Containerlab native configuration-save state is inconsistent")

    files = [(member, name) for member, name in members if member.isfile()]
    return {
        "definition_count": 1,
        "expanded_size_bytes": sum(member.size for member, _ in files),
        "image_references": sorted(set(references)),
        "images_included": False,
        "member_count": len(members),
        "containerlab": {
            "bundle_root": bundle_root,
            "mode": str(manifest["mode"]),
            "topology_relpath": topology_relpath,
            "topology_sha256": topology_sha256,
            "source_root_included": source_root_included,
            "labdir_base": labdir_base,
            "native_config_save_attempted": native_config_save_attempted,
            "native_config_save_rc": native_config_save_rc,
        },
    }


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
                references, requirements = _eve_image_references(handle, definitions)
                return {
                    "definition_count": len(definitions),
                    "expanded_size_bytes": sum(member.size for member, _ in files),
                    "image_references": references,
                    "image_requirements": requirements,
                    "images_included": False,
                    "member_count": len(members),
                }

            if platform == "containerlab":
                return _inspect_containerlab_archive(handle, members)

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


def _inspect_eve_images(
    path: Path,
    requirements: list[tuple[str, str]],
) -> dict[str, Any]:
    if not requirements:
        raise ValueError("EVE-NG image archive has no referenced base images")
    try:
        with tarfile.open(path, mode="r:*") as handle:
            members = _safe_members(handle)
            files = [name for member, name in members if member.isfile()]
            if not files:
                raise ValueError("EVE-NG image archive contains no files")
            allowed = (
                "qemu/",
                "iol/bin/",
                "dynamips/",
            )
            invalid = [name for name in files if not name.startswith(allowed)]
            if invalid:
                raise ValueError(
                    f"EVE-NG image archive contains an unsupported path: {invalid[0]}"
                )
            licence_files = [
                name
                for name in files
                if name.lower() in {"iol/bin/iourc", "iol/bin/iourc.txt"}
            ]
            if licence_files:
                raise ValueError(
                    "EVE-NG image archive must not contain IOL licence material"
                )

            selected: set[tuple[str, str]] = set()
            invalid_layout: list[str] = []
            for name in files:
                parts = PurePosixPath(name).parts
                if parts[0] == "qemu" and len(parts) >= 2:
                    selected.add(("qemu", parts[1]))
                elif parts[:2] == ("iol", "bin") and len(parts) == 3:
                    selected.add(("iol/bin", parts[2]))
                elif parts[0] == "dynamips" and len(parts) == 2:
                    selected.add(("dynamips", parts[1]))
                else:
                    invalid_layout.append(name)
            if invalid_layout:
                raise ValueError(
                    f"EVE-NG image archive contains an invalid image path: {invalid_layout[0]}"
                )

            missing: list[str] = []
            allowed_selected: set[tuple[str, str]] = set()
            for root_name, reference in requirements:
                if (
                    not reference
                    or reference in {".", ".."}
                    or PurePosixPath(reference).name != reference
                    or "\\" in reference
                ):
                    raise ValueError(
                        f"EVE-NG lab contains an unsafe image reference: {reference}"
                    )
                if root_name == "*":
                    matches = {
                        candidate for candidate in selected if candidate[1] == reference
                    }
                    if not matches:
                        missing.append(reference)
                    allowed_selected.update(matches)
                else:
                    candidate = (root_name, reference)
                    if candidate not in selected:
                        missing.append(f"{root_name}/{reference}")
                    allowed_selected.add(candidate)
            if missing:
                raise ValueError(
                    f"EVE-NG image archive is missing a referenced base: {missing[0]}"
                )
            extra = sorted(selected - allowed_selected)
            if extra:
                root_name, reference = extra[0]
                raise ValueError(
                    f"EVE-NG image archive contains an unreferenced base: {root_name}/{reference}"
                )
            return {
                "expanded_size_bytes": sum(
                    member.size for member, _ in members if member.isfile()
                ),
                "image_count": len(selected),
                "member_count": len(members),
            }
    except tarfile.TarError as exc:
        raise ValueError(
            f"image archive is not a readable tar archive: {path}"
        ) from exc


def inspect_migration_archive(
    *,
    platform: str,
    archive: str | Path,
    node_state: str | Path | None = None,
    images: str | Path | None = None,
    expected_sha256: str = "",
    node_state_expected_sha256: str = "",
    images_expected_sha256: str = "",
) -> dict[str, Any]:
    platform_name = str(platform or "").strip().lower()
    if platform_name not in SUPPORTED_PLATFORMS:
        raise ValueError("platform must be one of: " + ", ".join(SUPPORTED_PLATFORMS))

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

    image_report: dict[str, Any] | None = None
    image_path: Path | None = None
    if images:
        if platform_name != "eve-ng":
            raise ValueError("a separate image archive is only valid for EVE-NG")
        image_path = _regular_file(images, "image archive")
        image_checksum = _sha256(image_path)
        image_expected = _expected_checksum(
            images_expected_sha256,
            "image expected SHA-256",
        )
        if image_expected and image_checksum != image_expected:
            raise ValueError("image archive SHA-256 checksum does not match")
        image_report = {
            "path": str(image_path),
            "size_bytes": image_path.stat().st_size,
            "sha256": image_checksum,
            **_inspect_eve_images(image_path, primary["image_requirements"]),
        }
    elif images_expected_sha256:
        raise ValueError("image expected SHA-256 requires --images")

    warnings: list[str] = []
    images_included = bool(primary["images_included"] or image_report)
    if primary["image_references"] and not images_included:
        if platform_name == "containerlab":
            warnings.append(
                "referenced container images must be available on the target"
            )
        else:
            warnings.append("referenced base images must be available on the target")
    if platform_name == "eve-ng" and node_report is None:
        warnings.append("writable QEMU node state is not included")
    containerlab_metadata = primary.get("containerlab")
    if (
        platform_name == "containerlab"
        and isinstance(containerlab_metadata, dict)
        and containerlab_metadata.get("native_config_save_attempted")
        and containerlab_metadata.get("native_config_save_rc") != 0
    ):
        warnings.append(
            "Containerlab native configuration save did not complete; the source tree is retained"
        )

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
        "images_included": images_included,
        "images": image_report,
        "node_state": node_report,
        "containerlab": containerlab_metadata,
        "warnings": warnings,
    }


def _remote_capture_script(
    platform: str,
    *,
    node_state: bool = False,
    image_state: bool = False,
    include_images: bool = False,
    source_root: str = "",
    topology_relpath: str = "",
    source_labdir_base: str = "",
    target_labdir_base: str = "",
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
    if platform == "containerlab":
        capture_command = " ".join(
            [
                "python3 -c",
                shlex.quote(_CONTAINERLAB_CAPTURE_PROGRAM),
                "capture",
                shlex.quote(source_root),
                shlex.quote(topology_relpath),
                shlex.quote(source_labdir_base),
                shlex.quote(target_labdir_base),
            ]
        )
        assessment_command = " ".join(
            [
                "python3 -c",
                shlex.quote(_CONTAINERLAB_CAPTURE_PROGRAM),
                "assess",
                shlex.quote(source_root),
                shlex.quote(topology_relpath),
                shlex.quote(source_labdir_base),
                shlex.quote(target_labdir_base),
            ]
        )
        return f"""set -eu
required=$({assessment_command})
{capacity_check}exec {capture_command}
"""

    if platform == "eve-ng":
        compressor = "compressor='gzip -1'\ncommand -v pigz >/dev/null 2>&1 && compressor='pigz -1'"
        if image_state:
            image_command = (
                "python3 -c "
                + shlex.quote(_EVE_IMAGE_CAPTURE_PROGRAM)
                + " capture /opt/unetlab/labs /opt/unetlab/addons"
            )
            assessment_command = (
                "python3 -c "
                + shlex.quote(_EVE_IMAGE_CAPTURE_PROGRAM)
                + " assess /opt/unetlab/labs /opt/unetlab/addons"
            )
            return f"""set -eu
required=$({assessment_command})
{capacity_check}exec {image_command}
"""
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
{capacity_check}{compressor}
find . -type f -name '*.qcow2' -printf '%P\\0' | sort -z | \
  tar --null --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  --sparse -I "$compressor" -cf - --files-from=-
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
{capacity_check}{compressor}
exec tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  -I "$compressor" -cf - -C "$root" .
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
{capacity_check}compressor='gzip -1'
command -v pigz >/dev/null 2>&1 && compressor='pigz -1'
exec tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  --sparse -I "$compressor" -cf - -C "$root" "$@"
"""


def _remote_capture_assessment_script(
    platform: str,
    *,
    include_node_state: bool = False,
    include_images: bool = False,
    source_root: str = "",
    topology_relpath: str = "",
    source_labdir_base: str = "",
    target_labdir_base: str = "",
) -> str:
    if platform == "containerlab":
        assessment_command = " ".join(
            [
                "python3 -c",
                shlex.quote(_CONTAINERLAB_CAPTURE_PROGRAM),
                "assess",
                shlex.quote(source_root),
                shlex.quote(topology_relpath),
                shlex.quote(source_labdir_base),
                shlex.quote(target_labdir_base),
            ]
        )
        return f"""set -eu
primary_bytes=$({assessment_command})
printf 'primary_bytes=%s\nnode_state_bytes=0\nimage_bytes=0\n' "$primary_bytes"
"""

    if platform == "eve-ng":
        node_state_assessment = "node_state_bytes=0"
        image_assessment = "image_bytes=0"
        if include_images:
            image_command = (
                "python3 -c "
                + shlex.quote(_EVE_IMAGE_CAPTURE_PROGRAM)
                + " assess /opt/unetlab/labs /opt/unetlab/addons"
            )
            image_assessment = f"image_bytes=$({image_command})"
        if include_node_state:
            node_state_assessment = """node_root=/opt/unetlab/tmp
test -d "$node_root" || { echo 'EVE-NG node-state root not found' >&2; exit 20; }
cd "$node_root"
find . -type f -name '*.qcow2' -printf '%P\\n' -quit | grep -q . || {
  echo 'No EVE-NG QEMU node state was found' >&2
  exit 22
}
node_state_bytes=$(find . -type f -name '*.qcow2' -printf '%b\\n' | awk '{total += $1} END {printf "%.0f\\n", total * 512}')"""
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
primary_bytes=$(find "$root" -type f -printf '%b\\n' | awk '{{total += $1}} END {{printf "%.0f\\n", total * 512}}')
{node_state_assessment}
{image_assessment}
printf 'primary_bytes=%s\\nnode_state_bytes=%s\\nimage_bytes=%s\\n' "$primary_bytes" "$node_state_bytes" "$image_bytes"
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
primary_bytes=$(du -s --block-size=1 "$@" | awk '{{total += $1}} END {{printf "%.0f\\n", total}}')
printf 'primary_bytes=%s\\nnode_state_bytes=0\\nimage_bytes=0\\n' "$primary_bytes"
"""


def _ssh_capture_argv(
    *,
    host: str,
    user: str,
    port: int,
    identity_file: str | Path | None,
    become: bool,
    script: str,
    control_path: Path | None = None,
) -> list[str]:
    host_name = _ssh_name(host, "host")
    user_name = _ssh_name(user, "user") if user else ""
    if not 1 <= int(port) <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    target = f"{user_name}@{host_name}" if user_name else host_name
    argv = ["ssh", "-T", "-p", str(port)]
    if control_path is not None:
        argv.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPersist=30",
                "-o",
                f"ControlPath={control_path}",
            ]
        )
    if identity_file:
        identity = _regular_file(identity_file, "identity file")
        argv.extend(["-i", str(identity)])
    remote = ["sudo", "-n", "sh", "-c", script] if become else ["sh", "-c", script]
    return [*argv, target, shlex.join(remote)]


def _capture_error(result: subprocess.CompletedProcess[bytes]) -> ValueError:
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    lowered_detail = detail.lower()
    if (
        "no space left on device" in lowered_detail
        or "disk quota exceeded" in lowered_detail
    ):
        return ValueError(
            "insufficient disk space for lab capture: the output filesystem became full while writing the archive"
        )
    capacity_match = re.search(
        r"source requires at least (\d+) bytes; "
        r"output filesystem has (\d+) bytes available",
        detail,
        flags=re.IGNORECASE,
    )
    if capacity_match:
        required = int(capacity_match.group(1))
        available = int(capacity_match.group(2))
        return ValueError(
            "insufficient disk space for lab capture: source requires at least "
            f"{_format_bytes(required)}; output filesystem has "
            f"{_format_bytes(available)} available"
        )
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    concise = (
        "; ".join(lines[-3:])[-800:] or f"ssh exited with status {result.returncode}"
    )
    return ValueError(f"source capture failed: {concise}")


def _capture_requirements(argv: list[str]) -> dict[str, int]:
    try:
        result = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("ssh is not installed or is not available on PATH") from exc
    if result.returncode != 0:
        raise _capture_error(result)

    values: dict[str, int] = {}
    for raw_line in result.stdout.decode("utf-8", errors="replace").splitlines():
        key, separator, raw_value = raw_line.strip().partition("=")
        if not separator or key not in {
            "primary_bytes",
            "node_state_bytes",
            "image_bytes",
        }:
            raise ValueError("source capture assessment returned invalid output")
        if key in values:
            raise ValueError("source capture assessment returned a duplicate size")
        if not raw_value.isdigit():
            raise ValueError("source capture assessment returned an invalid size")
        values[key] = int(raw_value)
    if not {"primary_bytes", "node_state_bytes", "image_bytes"}.issubset(values):
        raise ValueError("source capture assessment did not return required sizes")
    return values


def _close_ssh_control(
    *,
    host: str,
    user: str,
    port: int,
    control_path: Path,
) -> None:
    host_name = _ssh_name(host, "host")
    user_name = _ssh_name(user, "user") if user else ""
    target = f"{user_name}@{host_name}" if user_name else host_name
    try:
        subprocess.run(
            [
                "ssh",
                "-O",
                "exit",
                "-S",
                str(control_path),
                "-p",
                str(port),
                target,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        pass


def _capture_stream(
    argv: list[str],
    candidate: Path,
    *,
    stage: str = "archive",
    expected_source_bytes: int = 0,
    progress: CaptureProgress | None = None,
) -> None:
    started = time.monotonic()
    stopped = threading.Event()

    def emit(phase: str, *, status: str = "running") -> None:
        if progress is None:
            return
        elapsed = max(0.0, time.monotonic() - started)
        try:
            written = candidate.stat().st_size
        except OSError:
            written = 0
        progress(
            {
                "phase": phase,
                "stage": stage,
                "status": status,
                "bytes_written": written,
                "expected_source_bytes": max(0, int(expected_source_bytes)),
                "elapsed_seconds": elapsed,
                "bytes_per_second": written / elapsed if elapsed > 0 else 0.0,
            }
        )

    def monitor() -> None:
        while not stopped.wait(1.0):
            emit("stream_progress")

    monitor_thread: threading.Thread | None = None
    emit("stream_started")
    if progress is not None:
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
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
        emit("stream_finished", status="failed")
        raise ValueError("ssh is not installed or is not available on PATH") from exc
    finally:
        stopped.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=2)
    if result.returncode == 0:
        os.chmod(candidate, 0o600)
        emit("stream_finished", status="ok")
        return
    emit("stream_finished", status="failed")
    raise _capture_error(result)


def _require_capture_capacity(
    *,
    destination: Path,
    primary_bytes: int,
    node_destination: Path | None,
    node_state_bytes: int,
    image_destination: Path | None,
    image_bytes: int,
) -> None:
    outputs = [(destination, primary_bytes, "lab capture")]
    if node_destination is not None:
        outputs.append((node_destination, node_state_bytes, "node-state capture"))
    if image_destination is not None:
        outputs.append((image_destination, image_bytes, "image capture"))
    filesystems: dict[int, tuple[Path, int, str]] = {}
    for output, required, operation in outputs:
        filesystem = _existing_filesystem_path(output.parent)
        device = filesystem.stat().st_dev
        if device in filesystems:
            prior_path, prior_required, _ = filesystems[device]
            filesystems[device] = (
                prior_path,
                prior_required + required,
                "lab capture",
            )
        else:
            filesystems[device] = (output.parent, required, operation)
    for path, required, operation in filesystems.values():
        _require_disk_space(path, required, operation)


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
            raise ValueError(
                f"output already exists: {path}; use --force to replace it"
            )
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


def _default_images_output(primary: Path) -> Path:
    name = primary.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.lower().endswith(suffix):
            return primary.with_name(name[: -len(suffix)] + ".images.tar.gz")
    return primary.with_name(name + ".images.tar.gz")


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
    images_output: str | Path | None = None,
    source_root: str = "",
    topology_relpath: str = "lab.clab.yml",
    source_labdir_base: str = "",
    target_labdir_base: str = "/var/lib/hybridops/containerlab/labdirs",
    force: bool = False,
    progress: CaptureProgress | None = None,
) -> dict[str, Any]:
    platform_name = str(platform or "").strip().lower()
    if platform_name not in SUPPORTED_PLATFORMS:
        raise ValueError("platform must be one of: " + ", ".join(SUPPORTED_PLATFORMS))
    if include_node_state and platform_name != "eve-ng":
        raise ValueError("separate node-state capture is only valid for EVE-NG")
    if node_state_output and not include_node_state:
        raise ValueError("--node-state-output requires --include-node-state")
    if images_output and not (include_images and platform_name == "eve-ng"):
        raise ValueError("--images-output requires EVE-NG --include-images")
    if platform_name == "containerlab":
        if not str(source_root or "").strip():
            raise ValueError("Containerlab capture requires --source-root")
        if include_images:
            raise ValueError(
                "Containerlab migration retains image references; --include-images is not supported"
            )
        if not str(topology_relpath or "").strip():
            raise ValueError("Containerlab capture requires --topology-relpath")
        if not str(target_labdir_base or "").strip():
            raise ValueError("Containerlab capture requires --target-labdir-base")
    elif source_root or source_labdir_base:
        raise ValueError(
            "--source-root and --source-labdir-base are only valid for Containerlab"
        )

    destination = _capture_destination(output, "output")
    node_destination: Path | None = None
    image_destination: Path | None = None
    if include_node_state:
        node_destination = (
            _capture_destination(node_state_output, "node-state output")
            if node_state_output
            else _default_node_state_output(destination)
        )
        if node_destination == destination:
            raise ValueError("node-state output must differ from the primary output")
    if include_images and platform_name == "eve-ng":
        image_destination = (
            _capture_destination(images_output, "images output")
            if images_output
            else _default_images_output(destination)
        )
        if image_destination in {destination, node_destination}:
            raise ValueError("images output must differ from other capture outputs")

    primary_candidate: Path | None = None
    node_candidate: Path | None = None
    image_candidate: Path | None = None
    control_root = Path(
        tempfile.mkdtemp(
            prefix="hyops-ssh-",
            dir="/tmp" if Path("/tmp").is_dir() else None,
        )
    )
    os.chmod(control_root, 0o700)
    control_path = control_root / "control"
    try:
        primary_candidate = _capture_candidate(destination, force)
        if node_destination is not None:
            node_candidate = _capture_candidate(node_destination, force)
        if image_destination is not None:
            image_candidate = _capture_candidate(image_destination, force)
        assessment_argv = _ssh_capture_argv(
            host=host,
            user=user,
            port=port,
            identity_file=identity_file,
            become=become,
            script=_remote_capture_assessment_script(
                platform_name,
                include_node_state=include_node_state,
                include_images=include_images,
                source_root=source_root,
                topology_relpath=topology_relpath,
                source_labdir_base=source_labdir_base,
                target_labdir_base=target_labdir_base,
            ),
            control_path=control_path,
        )
        if progress is not None:
            progress({"phase": "assessment_started", "stage": "assessment"})
        requirements = _capture_requirements(assessment_argv)
        if progress is not None:
            progress(
                {
                    "phase": "assessment_finished",
                    "primary_bytes": requirements["primary_bytes"],
                    "node_state_bytes": requirements["node_state_bytes"],
                    "image_bytes": requirements["image_bytes"],
                }
            )
        _require_capture_capacity(
            destination=destination,
            primary_bytes=requirements["primary_bytes"],
            node_destination=node_destination,
            node_state_bytes=requirements["node_state_bytes"],
            image_destination=image_destination,
            image_bytes=requirements["image_bytes"],
        )
        primary_argv = _ssh_capture_argv(
            host=host,
            user=user,
            port=port,
            identity_file=identity_file,
            become=become,
            script=_remote_capture_script(
                platform_name,
                include_images=include_images,
                source_root=source_root,
                topology_relpath=topology_relpath,
                source_labdir_base=source_labdir_base,
                target_labdir_base=target_labdir_base,
                output_available_bytes=_available_disk_bytes(destination.parent),
            ),
            control_path=control_path,
        )
        primary_stage = {
            "eve-ng": "lab_definitions",
            "gns3": "gns3_projects",
            "containerlab": "containerlab_source",
        }[platform_name]
        _capture_stream(
            primary_argv,
            primary_candidate,
            stage=primary_stage,
            expected_source_bytes=requirements["primary_bytes"],
            progress=progress,
        )
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
                control_path=control_path,
            )
            _capture_stream(
                node_argv,
                node_candidate,
                stage="node_state",
                expected_source_bytes=requirements["node_state_bytes"],
                progress=progress,
            )
        if image_candidate is not None and image_destination is not None:
            image_argv = _ssh_capture_argv(
                host=host,
                user=user,
                port=port,
                identity_file=identity_file,
                become=become,
                script=_remote_capture_script(
                    platform_name,
                    image_state=True,
                    output_available_bytes=_available_disk_bytes(
                        image_destination.parent
                    ),
                ),
                control_path=control_path,
            )
            _capture_stream(
                image_argv,
                image_candidate,
                stage="referenced_images",
                expected_source_bytes=requirements["image_bytes"],
                progress=progress,
            )

        if progress is not None:
            progress({"phase": "verification_started", "stage": "verification"})
        try:
            report = inspect_migration_archive(
                platform=platform_name,
                archive=primary_candidate,
                node_state=node_candidate,
                images=image_candidate,
            )
        except (OSError, ValueError):
            if progress is not None:
                progress(
                    {
                        "phase": "verification_finished",
                        "stage": "verification",
                        "status": "failed",
                    }
                )
            raise
        if progress is not None:
            progress(
                {
                    "phase": "verification_finished",
                    "stage": "verification",
                    "status": "ok",
                }
            )
        if node_candidate is not None and node_destination is not None:
            os.replace(node_candidate, node_destination)
        if image_candidate is not None and image_destination is not None:
            os.replace(image_candidate, image_destination)
        os.replace(primary_candidate, destination)
        report["archive"]["path"] = str(destination)
        if isinstance(report.get("node_state"), dict) and node_destination is not None:
            report["node_state"]["path"] = str(node_destination)
        if isinstance(report.get("images"), dict) and image_destination is not None:
            report["images"]["path"] = str(image_destination)
        report["source"] = {"host": host, "user": user or None}
        if platform_name == "containerlab":
            report["source"].update(
                {
                    "source_root": str(source_root),
                    "topology_relpath": str(topology_relpath),
                    "source_labdir_base": str(source_labdir_base) or None,
                    "target_labdir_base": str(target_labdir_base),
                }
            )
        return report
    finally:
        _close_ssh_control(
            host=host,
            user=user,
            port=port,
            control_path=control_path,
        )
        if primary_candidate is not None:
            primary_candidate.unlink(missing_ok=True)
        if node_candidate is not None:
            node_candidate.unlink(missing_ok=True)
        if image_candidate is not None:
            image_candidate.unlink(missing_ok=True)
        shutil.rmtree(control_root, ignore_errors=True)


def platform_for_blueprint(payload: dict[str, Any]) -> str:
    lifecycle = payload.get("archive_before_destroy")
    if isinstance(lifecycle, dict) and lifecycle:
        module_ref = str(lifecycle.get("module_ref") or "").strip()
        prefix = str(lifecycle.get("contract_prefix") or "").strip()
        if module_ref.endswith("/eve-ng-lab-archive") or prefix.startswith("eveng_"):
            return "eve-ng"
        if module_ref.endswith("/gns3-lab-archive") or prefix.startswith("gns3_"):
            return "gns3"
    steps = payload.get("steps")
    if isinstance(steps, list) and any(
        str(step.get("module_ref") or "").endswith("/containerlab-lab")
        for step in steps
        if isinstance(step, dict)
    ):
        return "containerlab"
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


def _containerlab_target_contract(payload: dict[str, Any]) -> tuple[str, str]:
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if not str(step.get("module_ref") or "").endswith("/containerlab-lab"):
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        topology_relpath = str(
            inputs.get("containerlab_lab_topology_relpath") or ""
        ).strip()
        labdir_base = str(inputs.get("containerlab_lab_labdir_base") or "").strip()
        if not topology_relpath or not labdir_base:
            raise ValueError(
                "target Containerlab blueprint has an incomplete recovery contract"
            )
        return topology_relpath, labdir_base
    raise ValueError("target blueprint has no Containerlab lab step")


def _publish_containerlab_latest(
    *,
    paths,
    archive_path: Path,
    checksum: str,
    metadata: dict[str, Any],
    image_references: list[str],
    force: bool,
) -> dict[str, Any]:
    from hyops.runtime.state import write_json_atomic, write_text_atomic

    recovery_dir = paths.root / "artifacts" / "containerlab" / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(recovery_dir, 0o700)
    latest = recovery_dir / "latest.tar.gz"
    if latest.exists() and latest.is_dir():
        raise ValueError(f"Containerlab latest recovery path is a directory: {latest}")
    latest_checksum = latest.with_name(latest.name + ".sha256")
    latest_metadata = latest.with_name(latest.name + ".json")
    markers = (latest, latest_checksum, latest_metadata)
    if any(path.exists() or path.is_symlink() for path in markers):
        complete = all(path.exists() or path.is_symlink() for path in markers)
        existing_checksum = ""
        if latest_checksum.is_file():
            existing_checksum = latest_checksum.read_text(encoding="utf-8").strip()
        if (not complete or existing_checksum != checksum) and not force:
            raise ValueError(
                "a different or incomplete Containerlab latest recovery set exists; "
                "use --force to replace it"
            )
    write_text_atomic(latest_checksum, checksum + "\n", mode=0o600)
    write_json_atomic(
        latest_metadata,
        {
            "schema": "hybridops.containerlab.latest/v1",
            "archive_sha256": checksum,
            "topology_sha256": metadata["topology_sha256"],
            "mode": metadata["mode"],
            "image_refs": image_references,
            "labdir_base": metadata["labdir_base"],
            "timestamp_archive": str(archive_path.resolve()),
        },
        mode=0o600,
    )
    fd, candidate_name = tempfile.mkstemp(
        prefix=".latest.",
        suffix=".candidate",
        dir=str(recovery_dir),
    )
    os.close(fd)
    candidate = Path(candidate_name)
    candidate.unlink()
    try:
        os.symlink(str(archive_path.resolve()), candidate)
        os.replace(candidate, latest)
    finally:
        candidate.unlink(missing_ok=True)
    return {
        "latest_path": str(latest),
        "sha256_path": str(latest_checksum),
        "metadata_path": str(latest_metadata),
    }


def _copy_verified(
    source: Path,
    destination: Path,
    checksum: str,
    *,
    stage: str,
    progress: CaptureProgress | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    if destination.is_symlink():
        raise ValueError(f"staged archive must not be a symbolic link: {destination}")
    if destination.exists() and not destination.is_file():
        raise ValueError(f"staged archive is not a regular file: {destination}")
    total = source.stat().st_size
    started = time.monotonic()
    written = 0
    finished = False

    def emit(phase: str, *, status: str = "running") -> None:
        if progress is None:
            return
        elapsed = max(0.0, time.monotonic() - started)
        progress(
            {
                "phase": phase,
                "stage": stage,
                "status": status,
                "bytes_written": written,
                "total_bytes": total,
                "elapsed_seconds": elapsed,
                "bytes_per_second": written / elapsed if elapsed > 0 else 0.0,
            }
        )

    emit("stage_started")
    try:
        if destination.is_file() and _sha256(destination) == checksum:
            written = total
            os.chmod(destination, 0o600)
            emit("stage_finished", status="skipped")
            finished = True
            return

        fd, candidate_name = tempfile.mkstemp(
            prefix=destination.name + ".",
            suffix=".candidate",
            dir=str(destination.parent),
        )
        candidate = Path(candidate_name)
        try:
            last_update = started
            with os.fdopen(fd, "wb") as target_handle, source.open("rb") as source_handle:
                while chunk := source_handle.read(1024 * 1024):
                    target_handle.write(chunk)
                    written += len(chunk)
                    now = time.monotonic()
                    if now - last_update >= 1.0:
                        emit("stage_progress")
                        last_update = now
                emit("stage_progress")
                target_handle.flush()
                os.fsync(target_handle.fileno())
            os.chmod(candidate, 0o600)
            emit("stage_verifying")
            if _sha256(candidate) != checksum:
                raise ValueError(
                    f"staged archive checksum verification failed: {source}"
                )
            os.replace(candidate, destination)
        finally:
            candidate.unlink(missing_ok=True)
        emit("stage_finished", status="ok")
        finished = True
    except Exception:
        if not finished:
            emit("stage_finished", status="failed")
        raise


def _write_record(path: Path, record: dict[str, Any]) -> None:
    from hyops.runtime.state import write_json_atomic

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    write_json_atomic(path, record, mode=0o600)


def _bundle_id(
    primary_checksum: str,
    node_checksum: str,
    image_checksum: str,
) -> str:
    identity = f"{primary_checksum}:{node_checksum}:{image_checksum}".encode("ascii")
    return hashlib.sha256(identity).hexdigest()[:16]


def stage_migration_archive(
    *,
    paths,
    payload: dict[str, Any],
    platform: str,
    archive: str | Path,
    node_state: str | Path | None = None,
    images: str | Path | None = None,
    expected_sha256: str = "",
    node_state_expected_sha256: str = "",
    images_expected_sha256: str = "",
    force: bool = False,
    progress: CaptureProgress | None = None,
) -> dict[str, Any]:
    platform_name = str(platform or "").strip().lower()
    target_platform = platform_for_blueprint(payload)
    if platform_name != target_platform:
        raise ValueError(
            f"source platform {platform_name} does not match target blueprint platform {target_platform}"
        )
    if progress is not None:
        progress({"phase": "import_verification_started", "stage": "verification"})
    try:
        inspection = inspect_migration_archive(
            platform=platform_name,
            archive=archive,
            node_state=node_state,
            images=images,
            expected_sha256=expected_sha256,
            node_state_expected_sha256=node_state_expected_sha256,
            images_expected_sha256=images_expected_sha256,
        )
    except Exception:
        if progress is not None:
            progress(
                {
                    "phase": "import_verification_finished",
                    "stage": "verification",
                    "status": "failed",
                }
            )
        raise
    if progress is not None:
        progress(
            {
                "phase": "import_verification_finished",
                "stage": "verification",
                "status": "ok",
            }
        )
    containerlab_metadata = inspection.get("containerlab")
    if platform_name == "containerlab":
        if not isinstance(containerlab_metadata, dict):
            raise ValueError("Containerlab migration archive has no recovery metadata")
        target_topology_relpath, target_labdir_base = _containerlab_target_contract(
            payload
        )
        if containerlab_metadata["topology_relpath"] != target_topology_relpath:
            raise ValueError(
                "Containerlab topology path does not match the target blueprint: "
                f"archive={containerlab_metadata['topology_relpath']} "
                f"target={target_topology_relpath}"
            )
        if containerlab_metadata["labdir_base"] != target_labdir_base:
            raise ValueError(
                "Containerlab labdir base does not match the target blueprint: "
                f"archive={containerlab_metadata['labdir_base']} "
                f"target={target_labdir_base}"
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
        str(existing_node.get("sha256") or "")
        if isinstance(existing_node, dict)
        else ""
    )
    image_inspection = inspection.get("images")
    image_checksum = (
        str(image_inspection.get("sha256") or "") if image_inspection else ""
    )
    existing_images = (existing or {}).get("images")
    existing_image_checksum = (
        str(existing_images.get("sha256") or "")
        if isinstance(existing_images, dict)
        else ""
    )
    if (
        existing
        and (
            existing_checksum,
            existing_node_checksum,
            existing_image_checksum,
        )
        != (
            inspection["archive"]["sha256"],
            node_checksum,
            image_checksum,
        )
        and not force
    ):
        raise ValueError(
            "a different migration bundle is already staged for this blueprint; use --force to replace the active record"
        )

    bundle_id = _bundle_id(
        inspection["archive"]["sha256"],
        node_checksum,
        image_checksum,
    )
    destination_root = (
        paths.root
        / "artifacts"
        / "lab-migrations"
        / _record_slug(blueprint_ref)
        / bundle_id
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
    if image_inspection:
        image_destination = destination_root / "labs.images.tar.gz"
        if not (
            image_destination.is_file()
            and _sha256(image_destination) == image_inspection["sha256"]
        ):
            copy_bytes += int(image_inspection["size_bytes"])
    if copy_bytes:
        _require_disk_space(destination_root, copy_bytes, "migration import")

    _copy_verified(
        Path(inspection["archive"]["path"]),
        archive_destination,
        inspection["archive"]["sha256"],
        stage="lab_definitions",
        progress=progress,
    )

    staged_node: dict[str, Any] | None = None
    if node_inspection:
        _copy_verified(
            Path(node_inspection["path"]),
            node_destination,
            node_inspection["sha256"],
            stage="node_state",
            progress=progress,
        )
        staged_node = {
            key: value for key, value in node_inspection.items() if key != "path"
        }
        staged_node["path"] = str(node_destination)

    staged_images: dict[str, Any] | None = None
    if image_inspection:
        _copy_verified(
            Path(image_inspection["path"]),
            image_destination,
            image_inspection["sha256"],
            stage="referenced_images",
            progress=progress,
        )
        staged_images = {
            key: value for key, value in image_inspection.items() if key != "path"
        }
        staged_images["path"] = str(image_destination)

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
        "images": staged_images,
        "definition_count": inspection["definition_count"],
        "image_references": inspection["image_references"],
        "images_included": inspection["images_included"],
        "containerlab": containerlab_metadata,
        "warnings": inspection["warnings"],
    }
    record["archive"]["path"] = str(archive_destination)
    if existing and (
        existing_checksum,
        existing_node_checksum,
        existing_image_checksum,
    ) != (
        record["archive"]["sha256"],
        node_checksum,
        image_checksum,
    ):
        record["supersedes"] = {
            "archive_sha256": existing_checksum,
            "node_state_sha256": existing_node_checksum,
            "images_sha256": existing_image_checksum,
            "imported_at": str(existing.get("imported_at") or ""),
        }
    if platform_name == "containerlab":
        record["containerlab_latest"] = _publish_containerlab_latest(
            paths=paths,
            archive_path=archive_destination,
            checksum=record["archive"]["sha256"],
            metadata=containerlab_metadata,
            image_references=record["image_references"],
            force=force,
        )
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


def _load_migration_record(*, paths, payload: dict[str, Any]) -> dict[str, Any] | None:
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
    if (
        record.get("schema_version") != SCHEMA_VERSION
        or record.get("kind") != RECORD_KIND
    ):
        raise ValueError(f"migration record has an unsupported schema: {path}")
    if record.get("status") != "verified":
        raise ValueError(f"migration record is not verified: {path}")
    if str(record.get("blueprint_ref") or "") != blueprint_ref:
        raise ValueError(f"migration record blueprint does not match {blueprint_ref}")
    platform = str(record.get("platform") or "")
    if platform != platform_for_blueprint(payload):
        raise ValueError(
            "migration record platform does not match the target blueprint"
        )
    return record


def load_migration_images(
    *,
    paths,
    payload: dict[str, Any],
) -> tuple[Path, str] | None:
    if not str(payload.get("blueprint_ref") or "").strip():
        return None
    record = _load_migration_record(paths=paths, payload=payload)
    if record is None:
        return None
    image_data = record.get("images")
    if image_data is None:
        return None
    if record.get("platform") != "eve-ng" or not isinstance(image_data, dict):
        raise ValueError("migration image record is invalid")
    return _verified_staged_file(
        paths=paths,
        value=image_data.get("path"),
        checksum=image_data.get("sha256"),
        field="migration image archive",
    )


def load_migration_archive(
    *,
    paths,
    payload: dict[str, Any],
) -> tuple[Path, str, Path | None, str, Path | None, str] | None:
    record = _load_migration_record(paths=paths, payload=payload)
    if record is None:
        return None
    blueprint_ref = str(payload.get("blueprint_ref") or "").strip()
    path = migration_record_path(paths, blueprint_ref)
    platform = str(record.get("platform") or "")

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

    image_path: Path | None = None
    image_checksum = ""
    image_data = record.get("images")
    if image_data is not None:
        if platform != "eve-ng" or not isinstance(image_data, dict):
            raise ValueError(f"migration image record is invalid: {path}")
        image_path, image_checksum = _verified_staged_file(
            paths=paths,
            value=image_data.get("path"),
            checksum=image_data.get("sha256"),
            field="migration image archive",
        )
    return (
        archive_path,
        checksum,
        node_path,
        node_checksum,
        image_path,
        image_checksum,
    )
