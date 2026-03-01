"""
purpose: Ansible configuration driver package.
Architecture Decision: ADR-N/A (config ansible driver)
maintainer: HybridOps.Studio
"""

from .driver import run
from .schema import validate_execution_schema

__all__ = ["run", "validate_execution_schema"]
