"""
purpose: Validate inputs for module org/gcp/project-factory.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any
import re

from hyops.runtime.gcp import normalize_billing_account_id
from hyops.validators.registry import ModuleValidationError


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

    def opt_list(key: str) -> list[Any]:
        v = inputs.get(key)
        if v is None:
            return []
        if not isinstance(v, list):
            raise ModuleValidationError(f"inputs.{key} must be a list when set")
        return v

    def opt_dict(key: str) -> dict[str, Any]:
        v = inputs.get(key)
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return v

    project_id = req_str("project_id")
    _ = req_str("region")

    # Upstream terraform-google-project-factory uses `billing_account` (string).
    # We accept both `billing_account` and the more explicit legacy alias
    # `billing_account_id` for operator ergonomics.
    billing_account = normalize_billing_account_id(opt_str("billing_account"))
    billing_account_id = normalize_billing_account_id(opt_str("billing_account_id"))
    if billing_account and billing_account_id and billing_account != billing_account_id:
        raise ModuleValidationError("inputs.billing_account and inputs.billing_account_id must match when both are set")
    effective_billing = billing_account or billing_account_id
    if not effective_billing:
        raise ModuleValidationError("one of inputs.billing_account or inputs.billing_account_id is required")

    name_prefix = opt_str("name_prefix")
    context_id = opt_str("context_id")

    if name_prefix and not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", name_prefix):
        raise ModuleValidationError("inputs.name_prefix must match [a-z0-9-] and start/end alnum")

    if context_id and not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", context_id):
        raise ModuleValidationError("inputs.context_id must match [a-z0-9-] and start/end alnum")

    # Organization/folder are recommended for enterprise governance but are
    # optional for consumer/trial accounts ("No organization" projects).
    org_id = opt_str("org_id")
    folder_id = opt_str("folder_id")
    if org_id and folder_id:
        raise ModuleValidationError("inputs.org_id and inputs.folder_id are mutually exclusive")

    _ = opt_list("activate_apis")
    _ = opt_dict("labels")

    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    if len(effective_billing) < 6:
        raise ModuleValidationError("inputs.billing_account looks invalid")
