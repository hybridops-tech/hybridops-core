"""hyops.validators.core.shared.vyos_image_artifact

purpose: Validate inputs for core/shared/vyos-image-artifact.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    check_no_placeholder,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_ARTIFACT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_FORMAT_RE = re.compile(r"^(qcow2|raw|img)$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def validate(inputs: dict[str, Any]) -> None:
    artifact_key = _req_str(inputs, "artifact_key")
    if not _ARTIFACT_KEY_RE.fullmatch(artifact_key):
        raise ModuleValidationError("inputs.artifact_key must match ^[a-z0-9][a-z0-9._-]{1,62}$")

    artifact_url = _req_str(inputs, "artifact_url")
    if "://" not in artifact_url:
        raise ModuleValidationError("inputs.artifact_url must look like a URL")

    artifact_format = _req_str(inputs, "artifact_format")
    if not _FORMAT_RE.fullmatch(artifact_format):
        raise ModuleValidationError("inputs.artifact_format must be one of: qcow2,raw,img")

    _opt_str(inputs, "artifact_version")
    artifact_sha256 = _opt_str(inputs, "artifact_sha256")
    if artifact_sha256 and (
        len(artifact_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in artifact_sha256)
    ):
        raise ModuleValidationError("inputs.artifact_sha256 must be a 64-character hex string when set")

    source_iso_url = _opt_str(inputs, "source_iso_url")
    if source_iso_url and "://" not in source_iso_url:
        raise ModuleValidationError("inputs.source_iso_url must look like a URL when set")

    _opt_str(inputs, "notes")
