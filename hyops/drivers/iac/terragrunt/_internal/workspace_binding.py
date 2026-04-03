"""Backend/workspace binding helpers for Terragrunt driver.

purpose: Persist and validate backend binding to prevent accidental cross-namespace
Terraform Cloud workspace drift for the same HybridOps module state slot.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
import re
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


_GCP_PROJECT_LINK_RE = re.compile(r"/projects/(?P<project>[^/]+)/")
_GCP_PROJECT_ID_RE = re.compile(r"^projects/(?P<project>[^/]+)/")
_GCP_CONN_NAME_RE = re.compile(r"^(?P<project>[^:]+):[^:]+:[^:]+$")


def _iter_output_strings(value: Any):
    if isinstance(value, str):
        v = value.strip()
        if v:
            yield v
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_output_strings(nested)
        return
    if isinstance(value, list):
        for nested in value:
            yield from _iter_output_strings(nested)


def infer_gcp_project_id_from_outputs(outputs: dict[str, Any] | None) -> str:
    if not isinstance(outputs, dict):
        return ""

    for key in ("project_id", "target_project_id", "network_project_id", "secret_project_id"):
        value = str(outputs.get(key) or "").strip()
        if value:
            return value

    for candidate in _iter_output_strings(outputs):
        for pattern in (_GCP_PROJECT_LINK_RE, _GCP_PROJECT_ID_RE, _GCP_CONN_NAME_RE):
            match = pattern.search(candidate)
            if match:
                project = str(match.group("project") or "").strip()
                if project:
                    return project

    return ""


def allow_backend_binding_rehome(
    *,
    state_root: Path,
    module_ref: str,
    state_instance: str | None,
    inputs: dict[str, Any],
) -> tuple[bool, str]:
    """Allow a narrow class of safe backend-binding moves.

    When a prior module state publishes project_id and the current resolved
    inputs target a different project_id, HybridOps prefers a fresh Terraform Cloud
    workspace over reusing the old state slot. This protects recovery flows
    where the env root project changes and the old workspace still points at the
    former project.
    """

    target_project_id = str(inputs.get("project_id") or "").strip()
    if not target_project_id:
        return False, ""

    try:
        prior = read_module_state(state_root, module_ref, state_instance=state_instance)
    except Exception:
        return False, ""

    prior_outputs = prior.get("outputs") or {}
    if not isinstance(prior_outputs, dict):
        prior_outputs = {}
    prior_project_id = infer_gcp_project_id_from_outputs(prior_outputs)
    if not prior_project_id or prior_project_id == target_project_id:
        return False, ""

    return (
        True,
        "backend binding rehome allowed because resolved project_id changed "
        f"from {prior_project_id} to {target_project_id} for {module_ref}"
    )


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
        "WORKSPACE_PREFIX/name_prefix, or TFC_ORG). HybridOps blocks this to prevent writing a module state slot "
        "to a different Terraform Cloud workspace. "
        "Fix the naming inputs to match the prior run, or set HYOPS_ALLOW_BACKEND_BINDING_DRIFT=1 only for an intentional migration "
        "and then import/reconcile resources before continuing."
    ), ""
