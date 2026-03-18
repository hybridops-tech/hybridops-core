"""hyops.validators.core.onprem.vyos_template_import

purpose: Validate inputs for core/onprem/vyos-template-import.
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


_TEMPLATE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,126}$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def validate(inputs: dict[str, Any]) -> None:
    template_key = _req_str(inputs, "template_key")
    if not _TEMPLATE_KEY_RE.fullmatch(template_key):
        raise ModuleValidationError("inputs.template_key must match ^[a-z0-9][a-z0-9._-]{1,62}$")

    template_name = _req_str(inputs, "template_name")
    if not _TEMPLATE_NAME_RE.fullmatch(template_name):
        raise ModuleValidationError(
            "inputs.template_name must match ^[A-Za-z0-9][A-Za-z0-9._-]{1,126}$"
        )

    template_vm_id = inputs.get("template_vm_id")
    if isinstance(template_vm_id, bool) or not isinstance(template_vm_id, int) or template_vm_id <= 0:
        raise ModuleValidationError("inputs.template_vm_id must be a positive integer")

    _opt_str(inputs, "template_image_version")
    source_url = _opt_str(inputs, "template_source_url")
    if source_url and "://" not in source_url:
        raise ModuleValidationError("inputs.template_source_url must look like a URL when set")
    _opt_str(inputs, "notes")
