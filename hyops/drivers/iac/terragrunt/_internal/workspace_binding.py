"""Backend/workspace binding helpers for Terragrunt driver.

purpose: Persist and validate backend binding to prevent accidental cross-namespace
Terraform Cloud workspace drift for the same HyOps module state slot.
Architecture Decision: ADR-N/A (backend binding guard)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.runtime.module_state import module_state_path, read_module_state


def build_backend_binding(
    *,
    backend_mode: str,
    workspace_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    mode = str(backend_mode or "").strip().lower() or "local"
    binding: dict[str, Any] = {"mode": mode}

    if mode != "cloud":
        return binding

    tfc: dict[str, Any] = {}
    if isinstance(workspace_policy, dict):
        host = str(workspace_policy.get("host") or "").strip()
        org = str(workspace_policy.get("org") or "").strip()
        workspace_name = str(workspace_policy.get("workspace_name") or "").strip()
        exec_mode = str(workspace_policy.get("mode") or "").strip().lower()
        provider = str(workspace_policy.get("provider") or "").strip().lower()

        if host:
            tfc["host"] = host
        if org:
            tfc["org"] = org
        if workspace_name:
            tfc["workspace_name"] = workspace_name
        if exec_mode:
            tfc["execution_mode"] = exec_mode
        if provider:
            tfc["provider"] = provider

    if tfc:
        binding["terraform_cloud"] = tfc

    return binding


def _cmp(a: Any, b: Any) -> bool:
    return str(a or "").strip() == str(b or "").strip()


def check_backend_binding_drift(
    *,
    state_root: Path,
    module_ref: str,
    state_instance: str | None,
    current_binding: dict[str, Any],
    allow_drift: bool,
) -> tuple[str, str]:
    """Compare current backend binding with prior module state for the same slot.

    Returns: (error_message, warning_message)
    """

    if allow_drift:
        return "", ""

    try:
        state_path = module_state_path(state_root, module_ref, state_instance=state_instance)
    except Exception as exc:
        return f"backend binding guard failed to resolve module state path: {exc}", ""

    if not state_path.exists():
        return "", ""

    try:
        prior = read_module_state(state_root, module_ref, state_instance=state_instance)
    except Exception as exc:
        return (
            f"backend binding guard failed to read module state: {state_path} ({exc})",
            "",
        )

    status = str(prior.get("status") or "").strip().lower()
    if status == "destroyed":
        return "", ""

    execution = prior.get("execution")
    if not isinstance(execution, dict):
        return "", ""

    prior_binding = execution.get("backend")
    if not isinstance(prior_binding, dict):
        # Legacy state: allow one-time transition and let the next successful run persist the binding.
        return "", (
            "backend binding guard skipped: prior module state has no execution.backend metadata "
            f"(legacy state at {state_path})"
        )

    prior_mode = str(prior_binding.get("mode") or "").strip().lower()
    cur_mode = str(current_binding.get("mode") or "").strip().lower()
    if prior_mode != cur_mode:
        return (
            "backend binding mismatch for module state slot: "
            f"state={state_path} previous.mode={prior_mode or '<unset>'} current.mode={cur_mode or '<unset>'}. "
            "This can mix Terraform state across namespaces/backends. "
            "Use the same --env/WORKSPACE_PREFIX/TFC_ORG/backend mode as the prior run, "
            "or set HYOPS_ALLOW_BACKEND_BINDING_DRIFT=1 only if you are intentionally migrating and will import/reconcile state."
        ), ""

    if cur_mode != "cloud":
        return "", ""

    prior_tfc = prior_binding.get("terraform_cloud")
    cur_tfc = current_binding.get("terraform_cloud")
    if not isinstance(prior_tfc, dict) or not isinstance(cur_tfc, dict):
        return "", ""

    mismatches: list[str] = []
    for key in ("host", "org", "workspace_name"):
        if not _cmp(prior_tfc.get(key), cur_tfc.get(key)):
            mismatches.append(
                f"{key}: previous={str(prior_tfc.get(key) or '<unset>')} current={str(cur_tfc.get(key) or '<unset>')}"
            )

    if not mismatches:
        return "", ""

    slot = str(module_ref or "").strip()
    inst = str(state_instance or "").strip()
    if inst:
        slot = f"{slot}#{inst}"
    mismatch_lines = "; ".join(mismatches)
    return (
        "Terraform Cloud workspace binding mismatch for module state slot "
        f"{slot}: {mismatch_lines}. "
        "This usually means the derived workspace namespace changed (for example: --env/context_id, "
        "WORKSPACE_PREFIX/name_prefix, or TFC_ORG). HyOps blocks this to prevent writing a module state slot "
        "to a different Terraform Cloud workspace. "
        "Fix the naming inputs to match the prior run, or set HYOPS_ALLOW_BACKEND_BINDING_DRIFT=1 only for an intentional migration "
        "and then import/reconcile resources before continuing."
    ), ""
