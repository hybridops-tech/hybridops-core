"""Validate platform/linux/containerlab-gui inputs."""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    require_bool,
    require_mapping,
    require_non_empty_str,
    require_port,
)
from hyops.validators.platform.linux._eve_ng_common import validate_target_access


_CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")


def _require_absolute(value: Any, field: str) -> str:
    path = require_non_empty_str(value, field)
    if not path.startswith("/"):
        raise ValueError(f"{field} must be an absolute path")
    return path


def _require_pinned_image(value: Any, field: str) -> str:
    image = require_non_empty_str(value, field)
    if ":" not in image.rsplit("/", 1)[-1] or image.endswith(":latest"):
        raise ValueError(f"{field} must use an explicit non-latest tag")
    return image


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/containerlab-gui",
        require_ubuntu=True,
        require_eveng=False,
        allow_ubuntu_24=True,
    )
    require_non_empty_str(
        data.get("containerlab_gui_role_fqcn"),
        "inputs.containerlab_gui_role_fqcn",
    )
    require_non_empty_str(
        data.get("containerlab_gui_operator_user"),
        "inputs.containerlab_gui_operator_user",
    )
    _require_absolute(
        data.get("containerlab_gui_labs_dir"),
        "inputs.containerlab_gui_labs_dir",
    )
    _require_absolute(
        data.get("containerlab_gui_state_dir"),
        "inputs.containerlab_gui_state_dir",
    )
    for key in ("containerlab_gui_api_name", "containerlab_gui_web_name"):
        value = require_non_empty_str(data.get(key), f"inputs.{key}")
        if not _CONTAINER_NAME_RE.fullmatch(value):
            raise ValueError(f"inputs.{key} is not a valid container name")
    _require_pinned_image(
        data.get("containerlab_gui_api_image"),
        "inputs.containerlab_gui_api_image",
    )
    _require_pinned_image(
        data.get("containerlab_gui_web_image"),
        "inputs.containerlab_gui_web_image",
    )
    api_port = require_port(
        data.get("containerlab_gui_api_port"),
        "inputs.containerlab_gui_api_port",
    )
    web_port = require_port(
        data.get("containerlab_gui_web_port"),
        "inputs.containerlab_gui_web_port",
    )
    if api_port == web_port:
        raise ValueError("Containerlab API and web ports must differ")
    manage_password = require_bool(
        data.get("containerlab_gui_manage_operator_password"),
        "inputs.containerlab_gui_manage_operator_password",
    )
    if manage_password:
        password = str(data.get("containerlab_gui_operator_password") or "").strip()
        password_env = str(
            data.get("containerlab_gui_operator_password_env") or ""
        ).strip()
        if not password and not password_env:
            raise ValueError(
                "inputs.containerlab_gui_operator_password or "
                "inputs.containerlab_gui_operator_password_env is required"
            )
        if password_env and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", password_env):
            raise ValueError(
                "inputs.containerlab_gui_operator_password_env must be an environment variable name"
            )
