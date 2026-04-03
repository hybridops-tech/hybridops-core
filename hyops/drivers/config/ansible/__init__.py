"""
purpose: Ansible configuration driver package.
maintainer: HybridOps.Tech
"""

from .driver import run
from .schema import validate_execution_schema

__all__ = ["run", "validate_execution_schema"]
