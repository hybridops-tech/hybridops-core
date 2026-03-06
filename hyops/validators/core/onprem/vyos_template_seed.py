"""hyops.validators.core.onprem.vyos_template_seed

purpose: Validate inputs for core/onprem/vyos-template-seed.
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_TEMPLATE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,126}$")


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


def _opt_int(inputs: dict[str, Any], key: str, *, minimum: int = 1) -> int:
    value = inputs.get(key)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ModuleValidationError(f"inputs.{key} must be an integer >= {minimum}")
    return value


def _opt_bool(inputs: dict[str, Any], key: str) -> None:
    value = inputs.get(key)
    if value is not None and not isinstance(value, bool):
        raise ModuleValidationError(f"inputs.{key} must be a boolean when set")


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
    _opt_str(inputs, "artifact_state_ref")
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
    template_source_url = _opt_str(inputs, "template_source_url")
    if template_source_url and "://" not in template_source_url:
        raise ModuleValidationError("inputs.template_source_url must look like a URL when set")

    image_source_url = _opt_str(inputs, "image_source_url")
    if image_source_url and "://" not in image_source_url:
        raise ModuleValidationError("inputs.image_source_url must look like a URL when set")

    image_format = _opt_str(inputs, "image_format")
    if image_format and image_format not in {"qcow2", "raw", "img", "auto"}:
        raise ModuleValidationError("inputs.image_format must be one of: auto,qcow2,raw,img")

    image_compression = _opt_str(inputs, "image_compression")
    if image_compression and image_compression not in {"auto", "none", "xz", "gz"}:
        raise ModuleValidationError("inputs.image_compression must be one of: auto,none,xz,gz")

    _opt_bool(inputs, "seed_if_missing")
    _opt_bool(inputs, "rebuild_if_exists")

    seed_command = _opt_str(inputs, "seed_command")
    if seed_command and "\n" in seed_command:
        raise ModuleValidationError("inputs.seed_command must be a single shell command when set")

    _opt_int(inputs, "seed_timeout_s", minimum=60)
    _opt_int(inputs, "cpu_cores", minimum=1)
    _opt_int(inputs, "memory_mb", minimum=512)

    _opt_str(inputs, "proxmox_host")
    _opt_str(inputs, "proxmox_node")
    _opt_str(inputs, "storage_vm")
    _opt_str(inputs, "network_bridge")
    _opt_str(inputs, "ssh_username")
    _opt_str(inputs, "ssh_private_key")
    _opt_str(inputs, "ci_username")
    _opt_str(inputs, "notes")
