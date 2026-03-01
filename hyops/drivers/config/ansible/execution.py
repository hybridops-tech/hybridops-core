"""Execution argument helpers for the Ansible config driver."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_execution_args(command_name: str, ansible_cfg: dict[str, Any]) -> tuple[list[str], str, str]:
    """Return (args, label, error_message_prefix) for the selected lifecycle command."""
    if command_name == "plan":
        return list(ansible_cfg["plan_args"]), "ansible_plan", "ansible plan failed"
    if command_name == "validate":
        return list(ansible_cfg["validate_args"]), "ansible_validate", "ansible validate failed"
    if command_name == "destroy":
        return list(ansible_cfg["destroy_args"]), "ansible_destroy", "ansible destroy failed"
    return list(ansible_cfg["apply_args"]), "ansible_apply", "ansible apply failed"


def build_playbook_argv(
    *,
    ansible_bin: str,
    playbook_path: Path,
    inventory_path: Path,
    extra_vars_path: Path,
    args: list[str],
) -> list[str]:
    return [
        ansible_bin,
        str(playbook_path),
        "-i",
        str(inventory_path),
        "-e",
        f"@{extra_vars_path}",
        *list(args),
    ]
