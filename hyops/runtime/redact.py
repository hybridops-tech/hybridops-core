"""Redaction utilities.

purpose: Prevent secret leakage in logs and evidence outputs.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Iterable


_DEFAULT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(\bauthorization:\s*bearer\s+)([^\s]+)"),
    re.compile(r"(?i)(\b(?:token|access_token|refresh_token|id_token|client_secret)\b\s*[:=]\s*)([^\s]+)"),
    re.compile(r'(?i)("?(?:token|access_token|refresh_token|id_token|client_secret)"?\s*:\s*")([^"]+)(")'),
    re.compile(r"(?i)(\b(?:password|passphrase|secret|api_key|apikey)\b\s*[:=]\s*)([^\s]+)"),
    re.compile(
        r"(?i)(\b(?:TFC_TOKEN|GITHUB_TOKEN|HCLOUD_TOKEN|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)\b\s*=\s*)([^\s]+)"
    ),
]


def redact_text(text: str, patterns: Iterable[re.Pattern[str]] | None = None) -> str:
    if not text:
        return ""
    pats = list(patterns) if patterns is not None else _DEFAULT_PATTERNS
    out = text

    for p in pats:
        if p.pattern.startswith('(?i)("?(?:token|access_token|refresh_token|id_token|client_secret)"?'):
            out = p.sub(r"\1***REDACTED***\3", out)
        else:
            out = p.sub(r"\1***REDACTED***", out)

    return out


def redact(text: str) -> str:
    return redact_text(text)