"""Operator-facing output helpers.

purpose: Keep concise command output independent from execution tooling.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re


_FAILURE_REPLACEMENTS = (
    ("ansible apply failed", "configuration apply failed"),
    ("ansible destroy failed", "configuration teardown failed"),
    ("ansible plan failed", "configuration plan failed"),
    ("ansible validate failed", "configuration validation failed"),
    ("terragrunt apply failed", "infrastructure apply failed"),
    ("terragrunt destroy failed", "infrastructure teardown failed"),
    ("terragrunt plan failed", "infrastructure plan failed"),
    ("terragrunt init failed", "infrastructure preparation failed"),
    ("packer build failed", "image build failed"),
    ("packer validate failed", "image validation failed"),
    ("packer init failed", "image preparation failed"),
)


def concise_error(message: str) -> str:
    text = str(message or "").strip()
    for internal, public in _FAILURE_REPLACEMENTS:
        text = text.replace(internal, public)
    text = re.sub(
        r"\s*\(open:\s*[^)]+/(?:ansible|terragrunt|packer)\.log\)",
        "",
        text,
    )
    return text.strip()
