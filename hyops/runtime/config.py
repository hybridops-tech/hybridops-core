"""Config helpers.

purpose: Provide consistent template write behaviour and basic validations.
maintainer: HybridOps
"""

from __future__ import annotations

from pathlib import Path
import os


def write_template_if_missing(path: Path, template: str, *, force: bool = False) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template, encoding="utf-8")
    os.chmod(path, 0o600)
    return True
