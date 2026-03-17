"""Preset overlay helpers for module inputs.

purpose: Resolve optional preset-based input overlays before driver execution.
Architecture Decision: ADR-N/A (preset overlays)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _as_preset_ref(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("inputs.preset_ref must be a string when set")
    return value.strip()


def resolve_preset_overlay(
    *,
    module_ref: str,
    defaults: dict[str, Any],
    spec_inputs: dict[str, Any],
    operator_inputs: dict[str, Any],
) -> dict[str, Any]:
    """
    Build resolved default inputs with optional preset overlay.

    Order:
      1) defaults
      2) preset defaults (if selected)
      3) operator inputs (applied later by caller)
      4) env overrides (applied later by caller)
    """
    out = dict(defaults)

    raw_presets = spec_inputs.get("presets")
    if raw_presets is None:
        # Fail fast when preset_ref is requested but no preset map exists.
        op_ref = _as_preset_ref(operator_inputs.get("preset_ref"))
        def_ref = _as_preset_ref(defaults.get("preset_ref"))
        if op_ref or def_ref:
            raise ValueError(
                f"{module_ref}: inputs.preset_ref provided but spec.inputs.presets is not defined"
            )
        return out

    presets = _as_mapping(raw_presets, "spec.inputs.presets")
    normalized: dict[str, dict[str, Any]] = {}
    for key, payload in presets.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("spec.inputs.presets keys must be non-empty strings")
        normalized[key.strip()] = _as_mapping(payload, f"spec.inputs.presets.{key}")

    default_ref = _as_preset_ref(defaults.get("preset_ref"))
    operator_ref = _as_preset_ref(operator_inputs.get("preset_ref"))
    selected = operator_ref or default_ref

    if not selected:
        return out

    if selected not in normalized:
        known = ", ".join(sorted(normalized.keys()))
        raise ValueError(
            f"{module_ref}: unknown inputs.preset_ref '{selected}' (available: {known})"
        )

    out.update(normalized[selected])
    out["preset_ref"] = selected
    return out

