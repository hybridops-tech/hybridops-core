"""
purpose: Validate inputs for org/gcp/gsm-eso-sa.
Architecture Decision: ADR-0206 (module execution contract v1)
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


PROJECT_ID_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
SERVICE_ACCOUNT_ID_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def validate(inputs: dict[str, Any]) -> None:
    project_id = _req_str(inputs, "project_id")
    eso_sa_name = _req_str(inputs, "eso_sa_name")
    eso_sa_display_name = _opt_str(inputs, "eso_sa_display_name")

    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    if not SERVICE_ACCOUNT_ID_RE.fullmatch(eso_sa_name):
        raise ModuleValidationError(
            "inputs.eso_sa_name must be 6-30 characters of lowercase letters, digits, or hyphens"
        )

    if eso_sa_display_name:
        marker = eso_sa_display_name.upper().replace("-", "_")
        if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
            raise ModuleValidationError("inputs.eso_sa_display_name must not contain placeholder values")
