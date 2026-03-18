"""hyops.validators.core.hetzner.vyos_image_register

purpose: Validate inputs for core/hetzner/vyos-image-register.
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


_IMAGE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_IMAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,126}$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def validate(inputs: dict[str, Any]) -> None:
    image_key = _req_str(inputs, "image_key")
    if not _IMAGE_KEY_RE.fullmatch(image_key):
        raise ModuleValidationError("inputs.image_key must match ^[a-z0-9][a-z0-9._-]{1,62}$")

    image_ref = _req_str(inputs, "image_ref")
    if not _IMAGE_REF_RE.fullmatch(image_ref):
        raise ModuleValidationError(
            "inputs.image_ref must match ^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,126}$"
        )

    source_url = _opt_str(inputs, "image_source_url")
    if source_url and "://" not in source_url:
        raise ModuleValidationError("inputs.image_source_url must look like a URL when set")

    _opt_str(inputs, "image_version")
    _opt_str(inputs, "notes")
