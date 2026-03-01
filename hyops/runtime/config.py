"""Config helpers.

purpose: Provide consistent template-on-missing behaviour and basic validations.
Architecture Decision: ADR-N/A (config helpers)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
import os


def write_template_if_missing(path: Path, template: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template, encoding="utf-8")
    os.chmod(path, 0o600)
    return True
