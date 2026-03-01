"""Terragrunt driver profile/template helpers (internal)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_INTERNAL_DIR = Path(__file__).resolve().parent
_DRIVER_DIR = _INTERNAL_DIR.parent
_PROFILES_DIR = _DRIVER_DIR / "profiles"
_TEMPLATES_DIR = _DRIVER_DIR / "templates"


def load_profile(profile_ref: str) -> tuple[dict[str, Any], Path | None, str]:
    if not profile_ref:
        return {}, None, ""

    p = _PROFILES_DIR / f"{profile_ref}.profile.yml"
    if not p.exists():
        # Backward-safe default: empty profile if not materialized yet.
        return {}, p, "profile not found"

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return {}, p, f"profile load failed: {e}"

    if not isinstance(raw, dict):
        return {}, p, "profile must be a mapping"

    return raw, p, ""


def _template_src_path(src_rel: str) -> Path:
    src = (_TEMPLATES_DIR / src_rel).resolve()
    try:
        src.relative_to(_TEMPLATES_DIR)
    except Exception as e:
        raise ValueError(f"template path escaped templates root: {src_rel}") from e
    return src


def _template_dst_path(stack_dir: Path, dst_rel: str) -> Path:
    dst = (stack_dir / dst_rel).resolve()
    try:
        dst.relative_to(stack_dir)
    except Exception as e:
        raise ValueError(f"template destination escaped stack root: {dst_rel}") from e
    return dst


def apply_templates(stack_dir: Path, profile: dict[str, Any]) -> None:
    templates = profile.get("templates") or []
    if not templates:
        return

    if not isinstance(templates, list):
        raise ValueError("profile.templates must be a list")

    for entry in templates:
        if not isinstance(entry, dict):
            raise ValueError("profile.templates entries must be mappings")

        src_rel = str(entry.get("src") or "").strip()
        dst_rel = str(entry.get("dst") or "").strip()
        if not src_rel or not dst_rel:
            raise ValueError("profile template entry requires src and dst")

        src = _template_src_path(src_rel)
        if not src.exists():
            raise FileNotFoundError(f"profile template not found: {src}")

        dst = _template_dst_path(stack_dir, dst_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def apply_profile_env(env: dict[str, str], profile: dict[str, Any]) -> None:
    profile_env = profile.get("env") or {}
    if not isinstance(profile_env, dict):
        raise ValueError("profile.env must be a mapping")

    for key, value in profile_env.items():
        name = str(key).strip()
        if not name:
            continue
        # Preserve explicit operator env/config (do not override non-empty values).
        if str(env.get(name) or "").strip():
            continue
        env[name] = str(value) if value is not None else ""

