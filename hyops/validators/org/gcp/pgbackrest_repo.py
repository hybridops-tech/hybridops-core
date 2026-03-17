"""
purpose: Validate inputs for module org/gcp/pgbackrest-repo.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_SA_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _reject_placeholder(value: str, field: str) -> None:
    marker = value.strip().upper().replace("-", "_")
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"{field} must not contain placeholder values (found {value!r})")


def validate(inputs: dict[str, Any]) -> None:
    def req_str(key: str) -> str:
        v = inputs.get(key)
        if not isinstance(v, str) or not v.strip():
            raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
        return v.strip()

    def opt_str(key: str) -> str:
        v = inputs.get(key)
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ModuleValidationError(f"inputs.{key} must be a string when set")
        return v.strip()

    def opt_bool(key: str) -> None:
        v = inputs.get(key)
        if v is None:
            return
        if not isinstance(v, bool):
            raise ModuleValidationError(f"inputs.{key} must be a boolean when set")

    def opt_num(key: str) -> float:
        v = inputs.get(key)
        if v is None:
            return 0.0
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ModuleValidationError(f"inputs.{key} must be a number when set")
        return float(v)

    project_id = req_str("project_id")
    bucket_name = req_str("bucket_name")
    _reject_placeholder(project_id, "inputs.project_id")
    _reject_placeholder(bucket_name, "inputs.bucket_name")

    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    if not _BUCKET_RE.fullmatch(bucket_name):
        raise ModuleValidationError(
            "inputs.bucket_name must be DNS-safe and match "
            "^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ "
            "(lowercase letters, digits, hyphens; example: 'hyops-dev-pgbackrest-a1')"
        )

    _ = req_str("location")
    storage_class = opt_str("storage_class") or "STANDARD"
    if storage_class and storage_class.upper() not in ("STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"):
        raise ModuleValidationError("inputs.storage_class must be one of: STANDARD, NEARLINE, COLDLINE, ARCHIVE")

    opt_bool("uniform_bucket_level_access")
    opt_bool("versioning_enabled")

    age = opt_num("lifecycle_delete_age_days")
    if age < 0:
        raise ModuleValidationError("inputs.lifecycle_delete_age_days must be >= 0")

    sa_id = opt_str("service_account_id") or "pgbackrest"
    _reject_placeholder(sa_id, "inputs.service_account_id")
    if not _SA_ID_RE.fullmatch(sa_id):
        raise ModuleValidationError(
            "inputs.service_account_id must match ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ (GCP service account id)"
        )

    _ = opt_str("service_account_display_name")
