"""hyops.validators.core.hetzner.vyos_image_seed

purpose: Validate inputs for core/hetzner/vyos-image-seed.
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_IMAGE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_IMAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,126}$")
_ARCH_RE = re.compile(r"^(x86|arm64)$")
_COMPRESSION_RE = re.compile(r"^(xz|bz2|gz|none|raw)$")
_SEED_LOCATION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
_SEED_SERVER_TYPE_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_QCOW2_URL_RE = re.compile(r"\.qcow2(?:\.(?:xz|gz|bz2))?(?:\?.*)?$", re.IGNORECASE)


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


def _req_bool(inputs: dict[str, Any], key: str) -> bool:
    value = inputs.get(key)
    if not isinstance(value, bool):
        raise ModuleValidationError(f"inputs.{key} must be true or false")
    return value


def validate(inputs: dict[str, Any]) -> None:
    image_key = _req_str(inputs, "image_key")
    if not _IMAGE_KEY_RE.fullmatch(image_key):
        raise ModuleValidationError("inputs.image_key must match ^[a-z0-9][a-z0-9._-]{1,62}$")

    image_ref = _opt_str(inputs, "image_ref")
    if image_ref and not _IMAGE_REF_RE.fullmatch(image_ref):
        raise ModuleValidationError(
            "inputs.image_ref must match ^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,126}$ when set"
        )

    _opt_str(inputs, "image_name")
    _opt_str(inputs, "image_description")
    _opt_str(inputs, "image_version")
    artifact_state_ref = _opt_str(inputs, "artifact_state_ref")
    _opt_str(inputs, "artifact_key")
    artifact_url = _opt_str(inputs, "artifact_url")
    if artifact_url and "://" not in artifact_url:
        raise ModuleValidationError("inputs.artifact_url must look like a URL when set")
    artifact_format = _opt_str(inputs, "artifact_format")
    if artifact_format and artifact_format not in {"qcow2", "raw", "img"}:
        raise ModuleValidationError("inputs.artifact_format must be one of: qcow2,raw,img")
    _opt_str(inputs, "artifact_version")
    artifact_sha256 = _opt_str(inputs, "artifact_sha256")
    if artifact_sha256 and (len(artifact_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in artifact_sha256)):
        raise ModuleValidationError("inputs.artifact_sha256 must be a 64-character hex string when set")
    source_iso_url = _opt_str(inputs, "source_iso_url")
    if source_iso_url and "://" not in source_iso_url:
        raise ModuleValidationError("inputs.source_iso_url must look like a URL when set")
    source_url = _opt_str(inputs, "image_source_url")
    if source_url and "://" not in source_url:
        raise ModuleValidationError("inputs.image_source_url must look like a URL when set")
    if source_url and not source_url.lower().startswith(("http://", "https://")):
        raise ModuleValidationError(
            "inputs.image_source_url must be an http(s) URL reachable by Hetzner rescue. "
            "If you only have a private/object-store URL, publish it first via core/shared/vyos-image-build."
        )

    architecture = _req_str(inputs, "image_architecture")
    if not _ARCH_RE.fullmatch(architecture):
        raise ModuleValidationError("inputs.image_architecture must be one of: x86, arm64")

    compression = _req_str(inputs, "image_compression")
    if not _COMPRESSION_RE.fullmatch(compression):
        raise ModuleValidationError("inputs.image_compression must be one of: xz, bz2, gz, none, raw")
    seed_location = _opt_str(inputs, "seed_location")
    if seed_location and not _SEED_LOCATION_RE.fullmatch(seed_location):
        raise ModuleValidationError(
            "inputs.seed_location must match ^[a-z0-9][a-z0-9-]{1,31}$ when set"
        )
    seed_server_type = _opt_str(inputs, "seed_server_type")
    if seed_server_type and not _SEED_SERVER_TYPE_RE.fullmatch(seed_server_type):
        raise ModuleValidationError(
            "inputs.seed_server_type must match ^[a-z][a-z0-9-]{1,31}$ when set"
        )
    wrapper_public_base_url = _opt_str(inputs, "seed_wrapper_public_base_url")
    if wrapper_public_base_url and "://" not in wrapper_public_base_url:
        raise ModuleValidationError("inputs.seed_wrapper_public_base_url must look like a URL when set")
    bind_port = inputs.get("seed_wrapper_bind_port")
    if not isinstance(bind_port, int) or bind_port < 1 or bind_port > 65535:
        raise ModuleValidationError("inputs.seed_wrapper_bind_port must be an integer between 1 and 65535")

    seed_if_missing = _req_bool(inputs, "seed_if_missing")
    seed_tool = _opt_str(inputs, "seed_tool")
    seed_command = _opt_str(inputs, "seed_command")
    timeout = inputs.get("seed_timeout_s")
    if not isinstance(timeout, int) or timeout < 60:
        raise ModuleValidationError("inputs.seed_timeout_s must be an integer >= 60")

    if not image_ref and seed_if_missing and not source_url and not seed_command and not artifact_state_ref and not artifact_url:
        raise ModuleValidationError(
            "inputs.image_source_url is required when inputs.image_ref is empty and inputs.seed_if_missing=true, "
            "unless inputs.artifact_state_ref/inputs.artifact_url or inputs.seed_command is provided explicitly. "
            "Recommended: run core/shared/vyos-image-build first and reference its state."
        )

    if not image_ref and seed_if_missing and not seed_command and not seed_tool:
        raise ModuleValidationError(
            "inputs.seed_tool is required when inputs.seed_command is not provided and inputs.seed_if_missing=true"
        )

    if (
        not image_ref
        and seed_if_missing
        and not seed_command
        and source_url
        and _QCOW2_URL_RE.search(source_url)
        and not wrapper_public_base_url
    ):
        raise ModuleValidationError(
            "inputs.seed_wrapper_public_base_url is required when inputs.image_source_url points to a qcow2 artifact "
            "and HyOps is expected to auto-wrap it for Hetzner. Set a publicly reachable base URL for the execution host, "
            "or provide inputs.seed_command explicitly."
        )

    _opt_str(inputs, "notes")
