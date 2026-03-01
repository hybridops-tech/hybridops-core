"""
purpose: Terragrunt module contract interface for module-specific behavior.
Architecture Decision: ADR-N/A (terragrunt contracts)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Any


class TerragruntModuleContract:
    def preprocess_inputs(
        self,
        *,
        command_name: str,
        module_ref: str,
        inputs: dict[str, Any],
        profile_policy: dict[str, Any],
        runtime: dict[str, Any],
        env: dict[str, str],
        credential_env: dict[str, str],
    ) -> tuple[dict[str, Any], list[str], str]:
        return inputs, [], ""

    def validate_push_to_netbox(
        self,
        *,
        command_name: str,
        module_ref: str,
        runtime: dict[str, Any],
    ) -> str:
        return ""
