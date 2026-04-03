"""Provider bootstrap guard helpers.

purpose: Guard driver execution when an init target is intentionally in bootstrap-only mode.
maintainer: HybridOps
"""

from __future__ import annotations

from pathlib import Path

from hyops.runtime.coerce import as_bool
from hyops.runtime.readiness import read_marker


_GCP_BOOTSTRAP_ALLOWED_MODULES = {"org/gcp/project-factory"}


def gcp_bootstrap_guard_message(*, runtime_root: Path, module_ref: str) -> str:
    """Return a block message when GCP init is in bootstrap-only mode."""

    meta_dir = runtime_root / "meta"
    try:
        marker = read_marker(meta_dir, "gcp")
    except Exception:
        return ""

    if str(marker.get("status") or "").strip().lower() != "ready":
        return ""

    context = marker.get("context")
    if not isinstance(context, dict):
        return ""

    if not as_bool(context.get("project_bootstrap_pending"), default=False):
        return ""

    if str(module_ref or "").strip() in _GCP_BOOTSTRAP_ALLOWED_MODULES:
        return ""

    project_id = str(context.get("project_id") or "").strip() or "<pending-project>"
    return (
        "gcp init is in bootstrap mode for target project "
        f"{project_id!r}. Only org/gcp/project-factory should run until the project exists. "
        "Run org/gcp/project-factory first, then rerun: "
        "hyops init gcp --env <env> --force --project-id <project-id> --region <region>"
    )
