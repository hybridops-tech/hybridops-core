"""
purpose: Module contract for org/gcp/cloudsql-postgresql Terragrunt behavior.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.gcp import diagnose_private_service_access_permissions

from .base import TerragruntModuleContract


class GcpCloudSqlPostgresqlContract(TerragruntModuleContract):
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

        normalized_command = str(command_name or "").strip().lower()
        if normalized_command not in ("apply", "deploy", "plan", "validate", "preflight"):
            return next_inputs, warnings, ""

        raw_create_private_service_connection = next_inputs.get("create_private_service_connection")
        if isinstance(raw_create_private_service_connection, bool):
            create_private_service_connection = raw_create_private_service_connection
        elif raw_create_private_service_connection is None:
            create_private_service_connection = True
        else:
            create_private_service_connection = str(raw_create_private_service_connection).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        if not create_private_service_connection:
            return next_inputs, warnings, ""

        project_id = str(next_inputs.get("project_id") or "").strip()
        network_project_id = str(next_inputs.get("network_project_id") or project_id).strip()
        if not project_id or not network_project_id:
            return next_inputs, warnings, ""

        impersonate_service_account = str(next_inputs.get("impersonate_service_account") or "").strip()
        if not impersonate_service_account:
            tfvars_path_raw = str(
                credential_env.get("HYOPS_GCP_TFVARS")
                or credential_env.get("HYOPS_GCP_CREDENTIALS_FILE")
                or ""
            ).strip()
            if tfvars_path_raw:
                try:
                    tfvars = parse_tfvars(Path(tfvars_path_raw).expanduser().resolve())
                except Exception as exc:
                    return next_inputs, warnings, f"failed to parse GCP credential tfvars: {exc}"
                impersonate_service_account = str(tfvars.get("impersonate_service_account") or "").strip()

        psa_ok, psa_detail = diagnose_private_service_access_permissions(
            project_id=project_id,
            network_project_id=network_project_id,
            impersonate_service_account=impersonate_service_account or None,
        )
        if not psa_ok:
            return next_inputs, warnings, "cloudsql private service networking preflight failed: " + psa_detail

        return next_inputs, warnings, ""
