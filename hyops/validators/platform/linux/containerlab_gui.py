"""Validate platform/linux/containerlab-gui inputs."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from hyops.validators.common import (
    require_bool,
    require_mapping,
    require_non_empty_str,
    require_port,
)
from hyops.validators.platform.linux._eve_ng_common import validate_target_access


_CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
_ACCOUNT_NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def _require_absolute(value: Any, field: str) -> str:
    path = require_non_empty_str(value, field)
    candidate = PurePosixPath(path)
    if (
        not path.startswith("/")
        or not path.rstrip("/")
        or ".." in candidate.parts
    ):
        raise ValueError(f"{field} must be an absolute non-root path")
    return path


def _require_pinned_image(value: Any, field: str) -> str:
    image = require_non_empty_str(value, field)
    image_leaf = image.rsplit("/", 1)[-1]
    if (
        ":" not in image_leaf
        or image_leaf.endswith(":")
        or image.endswith(":latest")
    ):
        raise ValueError(f"{field} must use an explicit non-latest tag")
    return image


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    target = validate_target_access(
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
    operator_user = require_non_empty_str(
        data.get("containerlab_gui_operator_user"),
        "inputs.containerlab_gui_operator_user",
    )
    deferred_local_user = (
        bool(target.get("local_execution"))
        and operator_user == "{{ ansible_user_id }}"
    )
    if (
        not deferred_local_user
        and (
            not _ACCOUNT_NAME_RE.fullmatch(operator_user)
            or operator_user == "root"
        )
    ):
        raise ValueError("inputs.containerlab_gui_operator_user is invalid")
    labs_dir = _require_absolute(
        data.get("containerlab_gui_labs_dir"),
        "inputs.containerlab_gui_labs_dir",
    )
    state_dir = _require_absolute(
        data.get("containerlab_gui_state_dir"),
        "inputs.containerlab_gui_state_dir",
    )
    try:
        PurePosixPath(state_dir).relative_to(PurePosixPath(labs_dir))
    except ValueError:
        pass
    else:
        raise ValueError(
            "inputs.containerlab_gui_state_dir must be outside containerlab_gui_labs_dir"
        )
    container_names: list[str] = []
    for key in ("containerlab_gui_api_name", "containerlab_gui_web_name"):
        value = require_non_empty_str(data.get(key), f"inputs.{key}")
        if not _CONTAINER_NAME_RE.fullmatch(value):
            raise ValueError(f"inputs.{key} is not a valid container name")
        container_names.append(value)
    if len(set(container_names)) != len(container_names):
        raise ValueError("Containerlab API and web container names must differ")
    group_names: list[str] = []
    for key in (
        "containerlab_gui_api_user_group",
        "containerlab_gui_api_superuser_group",
    ):
        value = require_non_empty_str(data.get(key), f"inputs.{key}")
        if not _ACCOUNT_NAME_RE.fullmatch(value):
            raise ValueError(f"inputs.{key} is not a valid group name")
        group_names.append(value)
    if len(set(group_names)) != len(group_names):
        raise ValueError("Containerlab API user and superuser groups must differ")
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
        raw_password = str(data.get("containerlab_gui_operator_password") or "")
        password = raw_password.strip()
        password_env = str(
            data.get("containerlab_gui_operator_password_env") or ""
        ).strip()
        if not password and not password_env:
            raise ValueError(
                "inputs.containerlab_gui_operator_password or "
                "inputs.containerlab_gui_operator_password_env is required"
            )
        if password and any(character in raw_password for character in ":\r\n"):
            raise ValueError(
                "inputs.containerlab_gui_operator_password contains an unsupported character"
            )
        if password_env and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", password_env):
            raise ValueError(
                "inputs.containerlab_gui_operator_password_env must be an environment variable name"
            )
