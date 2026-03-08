"""
purpose: Module contract for org/gcp/wan-vpn-to-edge Terragrunt behavior.
Architecture Decision: ADR-N/A (terragrunt contracts)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.runtime.vault import VaultAuth, read_env

from .base import TerragruntModuleContract


def _load_runtime_vault_env(runtime_root: Path) -> dict[str, str]:
    vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
    if not vault_file.exists():
        return {}
    return read_env(vault_file, VaultAuth())


class GcpWanVpnToEdgeContract(TerragruntModuleContract):
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
        next_inputs = dict(inputs)
        warnings: list[str] = []

        runtime_root_raw = str(runtime.get("root") or env.get("HYOPS_RUNTIME_ROOT") or "").strip()
        runtime_root = Path(runtime_root_raw).expanduser().resolve() if runtime_root_raw else None
        vault_env: dict[str, str] = {}

        if runtime_root is not None:
            try:
                vault_env = _load_runtime_vault_env(runtime_root)
            except Exception as exc:
                return next_inputs, warnings, f"failed to load runtime vault env: {exc}"

        def _resolve_secret(secret_key: str, env_key_field: str) -> tuple[str, str]:
            direct_value = str(next_inputs.get(secret_key) or "").strip()
            env_key = str(next_inputs.get(env_key_field) or "").strip()
            if direct_value:
                return direct_value, ""
            if not env_key:
                return "", f"missing {secret_key}: set inputs.{secret_key} or inputs.{env_key_field}"

            resolved = str(env.get(env_key) or vault_env.get(env_key) or "").strip()
            if resolved:
                return resolved, ""

            vault_path = ""
            if runtime_root is not None:
                vault_path = str((runtime_root / "vault" / "bootstrap.vault.env").resolve())
            hint = (
                f"missing {env_key}: provide it via shell env or store it in the runtime vault"
                + (f" ({vault_path})" if vault_path else "")
            )
            return "", hint

        shared_secret_a, err_a = _resolve_secret("shared_secret_a", "shared_secret_a_env")
        if err_a:
            return next_inputs, warnings, err_a
        shared_secret_b, err_b = _resolve_secret("shared_secret_b", "shared_secret_b_env")
        if err_b:
            return next_inputs, warnings, err_b

        next_inputs["shared_secret_a"] = shared_secret_a
        next_inputs["shared_secret_b"] = shared_secret_b
        next_inputs.pop("required_env", None)
        next_inputs.pop("shared_secret_a_env", None)
        next_inputs.pop("shared_secret_b_env", None)

        return next_inputs, warnings, ""
