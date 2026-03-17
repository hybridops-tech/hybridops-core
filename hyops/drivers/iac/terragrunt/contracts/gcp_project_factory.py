"""
purpose: Module contract for org/gcp/project-factory Terragrunt behavior.
Architecture Decision: ADR-N/A (terragrunt contracts)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import TerragruntModuleContract
from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.gcp import (
    diagnose_billing_association_permission,
    diagnose_project_access,
    normalize_billing_account_id,
)
from hyops.runtime.kv import read_kv_file


class GcpProjectFactoryContract(TerragruntModuleContract):
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

        # HyOps-friendly alias: billing_account_id -> billing_account
        billing_account = normalize_billing_account_id(str(next_inputs.get("billing_account") or "").strip())
        billing_account_id = normalize_billing_account_id(str(next_inputs.get("billing_account_id") or "").strip())
        if not billing_account and not billing_account_id:
            runtime_root_raw = str(runtime.get("root") or "").strip()
            if runtime_root_raw:
                config_path = Path(runtime_root_raw).expanduser().resolve() / "config" / "gcp.conf"
                if config_path.exists():
                    try:
                        cfg = read_kv_file(config_path)
                    except Exception:
                        cfg = {}
                    billing_account_id = normalize_billing_account_id(
                        str(cfg.get("GCP_BILLING_ACCOUNT_ID") or "").strip()
                    )
        if not billing_account and billing_account_id:
            next_inputs["billing_account"] = billing_account_id
            billing_account = billing_account_id
        if "billing_account_id" in next_inputs:
            next_inputs.pop("billing_account_id", None)

        # Upstream module requires `name`. We default to project_id (stable and
        # predictable) unless the operator explicitly sets it.
        name = str(next_inputs.get("name") or "").strip()
        if not name:
            project_id = str(next_inputs.get("project_id") or "").strip()
            if project_id:
                next_inputs["name"] = project_id
            else:
                # Keep this best-effort; validator should catch missing project_id.
                next_inputs["name"] = "hyops-gcp-project"

        # If neither org_id nor folder_id is set, we intentionally allow consumer/trial
        # mode ("No organization"), but surface a hint so operators understand the tradeoff.
        org_id = str(next_inputs.get("org_id") or "").strip()
        folder_id = str(next_inputs.get("folder_id") or "").strip()
        if not org_id and not folder_id:
            warnings.append(
                "gcp project-factory: org_id/folder_id not set; project will be created under 'No organization' when permitted. "
                "For enterprise governance, set one of: inputs.org_id or inputs.folder_id."
            )

        # Keep HyOps naming fields in the runtime inputs file (used by root.hcl to
        # compute a stable workspace name), but do not require them here.
        _ = str(next_inputs.get("name_prefix") or "").strip()
        _ = str(next_inputs.get("context_id") or "").strip()

        project_id = str(next_inputs.get("project_id") or "").strip()
        impersonate_service_account = ""
        tfvars_path_raw = str(
            credential_env.get("HYOPS_GCP_TFVARS")
            or credential_env.get("HYOPS_GCP_CREDENTIALS_FILE")
            or ""
        ).strip()
        if tfvars_path_raw:
            try:
                tfvars = parse_tfvars(Path(tfvars_path_raw).expanduser().resolve())
            except Exception:
                tfvars = {}
            impersonate_service_account = str(tfvars.get("impersonate_service_account") or "").strip()

        if project_id:
            project_ok, _project_detail = diagnose_project_access(
                project_id,
                impersonate_service_account=impersonate_service_account or None,
            )
            if project_ok:
                warnings.append(
                    f"gcp project-factory: target project {project_id} already exists and is accessible; skipping billing-association preflight"
                )
                return next_inputs, warnings, ""

        if not billing_account:
            # Validator should already block this; keep a clear contract message
            # for cases where contract is used without validator (e.g. direct driver).
            return next_inputs, warnings, (
                "missing billing account: set inputs.billing_account (or inputs.billing_account_id) for org/gcp/project-factory"
            )

        billing_ok, billing_detail, _ = diagnose_billing_association_permission(billing_account)
        if not billing_ok:
            detail = billing_detail or (
                f"current ADC lacks billing.resourceAssociations.create on billingAccounts/{billing_account}"
            )
            return next_inputs, warnings, (
                "gcp project-factory billing preflight failed: "
                + detail
            )

        return next_inputs, warnings, ""
