"""hyops.validators.core.onprem.vyos_template_seed

purpose: Validate inputs for core/onprem/vyos-template-seed.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    check_no_placeholder,
    normalize_required_env,
    opt_bool,
    opt_int,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_TEMPLATE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,126}$")
_GCS_ENV_KEYS = (
    "HYOPS_VYOS_GCS_SA_JSON",
    "HYOPS_VYOS_GCS_SA_JSON_FILE",
)
_GCS_URL_PREFIXES = (
    "gs://",
    "https://storage.googleapis.com/",
)


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def _opt_bool(inputs: dict[str, Any], key: str) -> bool | None:
    return opt_bool(inputs.get(key), f"inputs.{key}")


def _opt_int(inputs: dict[str, Any], key: str, *, minimum: int | None = None) -> int | None:
    return opt_int(inputs.get(key), f"inputs.{key}", minimum=minimum)


def _looks_like_private_gcs_source(*, artifact_state_ref: str, artifact_url: str, image_source_url: str, template_source_url: str) -> bool:
    if artifact_state_ref.startswith("core/shared/vyos-image-build") or artifact_state_ref.startswith("core/shared/vyos-image-artifact"):
        return True
    return any(url.startswith("gs://") for url in (artifact_url, image_source_url, template_source_url) if url)


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

    try:
        required_env = normalize_required_env(inputs.get("required_env"), "inputs.required_env")
    except ValueError as exc:
        raise ModuleValidationError(str(exc)) from exc

    _opt_str(inputs, "template_image_version")
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

    if _looks_like_private_gcs_source(
        artifact_state_ref=artifact_state_ref,
        artifact_url=artifact_url,
        image_source_url=image_source_url,
        template_source_url=template_source_url,
    ) and not any(env_key in required_env for env_key in _GCS_ENV_KEYS):
        raise ModuleValidationError(
            "inputs.required_env must include HYOPS_VYOS_GCS_SA_JSON or HYOPS_VYOS_GCS_SA_JSON_FILE "
            "when the template source resolves to a private GCS-backed artifact"
        )
