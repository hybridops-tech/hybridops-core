"""Exit codes.

purpose: Provide stable, documented exit codes for operator commands.
Architecture Decision: ADR-N/A (exit codes)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

OK = 0
TEMPLATE_WRITTEN = 10
CONFIG_INVALID = 11
DEPENDENCY_MISSING = 12
REMOTE_FAILED = 20
SECRETS_FAILED = 21
INTERNAL_ERROR = 30
OPERATOR_ERROR = 2

CONFIG_TEMPLATE_WRITTEN = TEMPLATE_WRITTEN
TARGET_EXEC_FAILURE = REMOTE_FAILED
VAULT_FAILURE = SECRETS_FAILED
WRITE_FAILURE = INTERNAL_ERROR