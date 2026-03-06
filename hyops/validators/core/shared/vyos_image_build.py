"""hyops.validators.core.shared.vyos_image_build

purpose: Validate inputs for core/shared/vyos-image-build.
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_ARTIFACT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_FORMAT_RE = re.compile(r"^(qcow2|raw|img)$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    token = value.strip()
    marker = token.upper().replace("-", "_")
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"inputs.{key} must not contain placeholder values (found {token!r})")
    return token


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ModuleValidationError(f"inputs.{key} must be a string when set")
    token = value.strip()
    if token:
        marker = token.upper().replace("-", "_")
        if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
            raise ModuleValidationError(f"inputs.{key} must not contain placeholder values (found {token!r})")
    return token


def _opt_bool(inputs: dict[str, Any], key: str) -> bool:
    value = inputs.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ModuleValidationError(f"inputs.{key} must be a boolean when set")
    return value


def validate(inputs: dict[str, Any]) -> None:
    artifact_key = _req_str(inputs, "artifact_key")
    if not _ARTIFACT_KEY_RE.fullmatch(artifact_key):
        raise ModuleValidationError("inputs.artifact_key must match ^[a-z0-9][a-z0-9._-]{1,62}$")

    artifact_format = _req_str(inputs, "artifact_format")
    if not _FORMAT_RE.fullmatch(artifact_format):
        raise ModuleValidationError("inputs.artifact_format must be one of: qcow2,raw,img")

    source_iso_url = _opt_str(inputs, "source_iso_url")
    if source_iso_url and "://" not in source_iso_url:
        raise ModuleValidationError("inputs.source_iso_url must look like a URL when set")
    allow_iso_build = _opt_bool(inputs, "allow_iso_build")
    if source_iso_url.lower().endswith(".iso") and not allow_iso_build:
        raise ModuleValidationError(
            "inputs.source_iso_url points to an ISO, but ISO build is disabled by default. "
            "Use a prebuilt qcow2/raw artifact URL for the production path, or set "
            "inputs.allow_iso_build=true to opt into the ISO/Packer build path."
        )

    artifact_local_path = _opt_str(inputs, "artifact_local_path")
    artifact_url = _opt_str(inputs, "artifact_url")
    repo_state_ref = _opt_str(inputs, "repo_state_ref")
    build_command = _opt_str(inputs, "build_command")
    publish_command = _opt_str(inputs, "publish_command")
    smoke_verify_command = _opt_str(inputs, "smoke_verify_command")
    _opt_str(inputs, "build_workdir")
    _opt_str(inputs, "smoke_verify_workdir")
    _opt_str(inputs, "publish_workdir")
    _opt_str(inputs, "artifact_version")
    _opt_str(inputs, "notes")
    smoke_verify_required = _opt_bool(inputs, "smoke_verify_required")

    artifact_sha256 = _opt_str(inputs, "artifact_sha256")
    if artifact_sha256 and (
        len(artifact_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in artifact_sha256)
    ):
        raise ModuleValidationError("inputs.artifact_sha256 must be a 64-character hex string when set")

    if not artifact_local_path and not artifact_url:
        raise ModuleValidationError(
            "inputs.artifact_local_path or inputs.artifact_url is required "
            "(local build path for shared artifact output, or a pre-published artifact URL)",
        )
    if artifact_local_path and artifact_local_path.endswith("/"):
        raise ModuleValidationError("inputs.artifact_local_path must point to a file, not a directory")
    if artifact_url and "://" not in artifact_url:
        raise ModuleValidationError("inputs.artifact_url must look like a URL when set")
    if repo_state_ref and "/" not in repo_state_ref:
        raise ModuleValidationError("inputs.repo_state_ref must look like a module state ref when set")
    if artifact_local_path and not build_command and not artifact_url and not publish_command:
        raise ModuleValidationError(
            "inputs.build_command is required when only inputs.artifact_local_path is provided "
            "and no published artifact URL exists yet",
        )
    if publish_command and not artifact_local_path:
        raise ModuleValidationError("inputs.artifact_local_path is required when inputs.publish_command is set")
    if publish_command and not artifact_url and not repo_state_ref:
        raise ModuleValidationError(
            "inputs.publish_command without inputs.artifact_url should usually be paired with inputs.repo_state_ref "
            "or a publish command that prints the final URL on stdout",
        )
    if smoke_verify_command and "\n" in smoke_verify_command:
        raise ModuleValidationError("inputs.smoke_verify_command must be a single shell command when set")
