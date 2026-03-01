"""
purpose: Validate inputs for module org/aws/pgbackrest-repo.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d$")
_IAM_USER_RE = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")


def _looks_like_s3_bucket(name: str) -> bool:
    if len(name) < 3 or len(name) > 63:
        return False
    if name.lower() != name:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", name):
        return False
    if ".." in name or ".-" in name or "-." in name:
        return False
    # Reject IP-like names.
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", name):
        return False
    return True


def validate(inputs: dict[str, Any]) -> None:
    def req_str(key: str) -> str:
        v = inputs.get(key)
        if not isinstance(v, str) or not v.strip():
            raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
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

    def opt_dict(key: str) -> dict[str, Any]:
        v = inputs.get(key)
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return v

    region = req_str("aws_region")
    if not _REGION_RE.fullmatch(region):
        raise ModuleValidationError("inputs.aws_region must look like an AWS region, e.g. us-east-1")

    bucket_name = req_str("bucket_name")
    if not _looks_like_s3_bucket(bucket_name):
        raise ModuleValidationError("inputs.bucket_name is not a valid S3 bucket name")

    iam_user_name = req_str("iam_user_name")
    if not _IAM_USER_RE.fullmatch(iam_user_name):
        raise ModuleValidationError(
            "inputs.iam_user_name must match ^[A-Za-z0-9+=,.@_-]{1,64}$"
        )

    opt_bool("force_destroy")
    opt_bool("versioning_enabled")

    lifecycle_days = opt_num("lifecycle_delete_age_days")
    if lifecycle_days < 0:
        raise ModuleValidationError("inputs.lifecycle_delete_age_days must be >= 0")

    sse_algorithm = req_str("sse_algorithm").lower()
    if sse_algorithm not in ("aes256", "aws:kms"):
        raise ModuleValidationError("inputs.sse_algorithm must be AES256 or aws:kms")

    kms_key_arn = str(inputs.get("kms_key_arn") or "").strip()
    if sse_algorithm == "aws:kms" and not kms_key_arn:
        raise ModuleValidationError("inputs.kms_key_arn is required when inputs.sse_algorithm=aws:kms")

    tags = opt_dict("tags")
    for k, v in tags.items():
        if not isinstance(k, str) or not k.strip():
            raise ModuleValidationError("inputs.tags keys must be non-empty strings")
        if not isinstance(v, str):
            raise ModuleValidationError("inputs.tags values must be strings")
