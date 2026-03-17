"""
purpose: Validate inputs for module org/gcp/wan-cloud-router.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    v = inputs.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    return v.strip()


def _asn(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModuleValidationError(f"inputs.{key} must be a number")
    n = int(value)
    if n < 1 or n > 4294967294:
        raise ModuleValidationError(f"inputs.{key} must be in range 1..4294967294")
    return n


def validate(inputs: dict[str, Any]) -> None:
    project_id = _req_str(inputs, "project_id")
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    _req_str(inputs, "region")
    _req_str(inputs, "network_self_link")
    _req_str(inputs, "router_name")

    _asn(inputs.get("bgp_asn"), "bgp_asn")
