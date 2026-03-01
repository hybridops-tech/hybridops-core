"""
purpose: Validate inputs for platform/onprem/control-node module.
Architecture Decision: ADR-N/A (onprem control-node validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Any

from ._proxmox_vm import validate_single_vm_inputs


def validate(inputs: dict[str, Any]) -> None:
    validate_single_vm_inputs(inputs)

