"""hyops.validators.core.shared.vyos_image_build

purpose: Validate inputs for core/shared/vyos-image-build.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import normalize_required_env
from hyops.validators.registry import ModuleValidationError


_ARTIFACT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_FORMAT_RE = re.compile(r"^(qcow2|raw|img)$")
_GCS_PUBLISH_ENV_KEYS = (
    "HYOPS_VYOS_GCS_SA_JSON",
    "HYOPS_VYOS_GCS_SA_JSON_FILE",
)
_GCS_ARTIFACT_URL_PREFIXES = (
    "gs://",
    "https://storage.googleapis.com/",
)


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


def _derive_publish_backend(*, inputs: dict[str, Any], repo_state_ref: str, artifact_url: str) -> str:
    backend = _opt_str(inputs, "backend").lower()
    if backend:
        return backend
    if repo_state_ref.startswith("org/gcp/object-repo"):
        return "gcs"
    if artifact_url.startswith(_GCS_ARTIFACT_URL_PREFIXES):
        return "gcs"
    return ""


def validate(inputs: dict[str, Any]) -> None:
    artifact_key = _req_str(inputs, "artifact_key")
    if not _ARTIFACT_KEY_RE.fullmatch(artifact_key):
        raise ModuleValidationError("inputs.artifact_key must match ^[a-z0-9][a-z0-9._-]{1,62}$")

    artifact_format = _req_str(inputs, "artifact_format")
    if not _FORMAT_RE.fullmatch(artifact_format):
        raise ModuleValidationError("inputs.artifact_format must be one of: qcow2,raw,img")

    try:
        required_env = normalize_required_env(inputs.get("required_env"), "inputs.required_env")
    except ValueError as exc:
        raise ModuleValidationError(str(exc)) from exc

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
    if build_command.endswith("/build-vyos-qcow2.sh") and not artifact_url:
        if not source_iso_url:
            raise ModuleValidationError(
                "inputs.source_iso_url is required when using the packaged build-vyos-qcow2.sh wrapper "
                "without a pre-published inputs.artifact_url"
            )
        if not allow_iso_build:
            raise ModuleValidationError(
                "inputs.allow_iso_build must be true when using the packaged build-vyos-qcow2.sh wrapper"
            )
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
    if publish_command and _derive_publish_backend(inputs=inputs, repo_state_ref=repo_state_ref, artifact_url=artifact_url) == "gcs":
        if not any(env_key in required_env for env_key in _GCS_PUBLISH_ENV_KEYS):
            raise ModuleValidationError(
                "inputs.required_env must include HYOPS_VYOS_GCS_SA_JSON or HYOPS_VYOS_GCS_SA_JSON_FILE "
                "when the publish path targets a GCS-backed object repo"
            )
    if smoke_verify_command and "\n" in smoke_verify_command:
        raise ModuleValidationError("inputs.smoke_verify_command must be a single shell command when set")
