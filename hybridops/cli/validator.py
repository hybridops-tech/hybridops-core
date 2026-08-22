"""
CLI Module Validator for HybridOps Core.

Provides diagnostic utilities to validate CLI configurations, schema contracts,
and execution environment health before workflow execution.
"""

from typing import Dict, Any, List, Optional
import os
import sys

class CLIValidator:
    """Validates execution environments and configurations for HybridOps CLI."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    def validate_environment(self) -> Dict[str, Any]:
        """
        Check execution environment readiness.
        
        Returns:
            Dict containing validation status and diagnostic details.
        """
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        is_supported = sys.version_info >= (3, 8)
        
        return {
            "status": "success" if is_supported else "failed",
            "python_version": python_version,
            "supported": is_supported,
            "env_vars_present": "HYBRID_OPS_ENV" in os.environ
        }

    def validate_schema(self, schema_data: Dict[str, Any], required_keys: List[str]) -> Dict[str, Any]:
        """
        Validate presence of required keys in schema contracts.
        
        Args:
            schema_data: Input dictionary to validate.
            required_keys: List of expected key names.
            
        Returns:
            Dict containing validation outcome and missing keys if any.
        """
        missing_keys = [key for key in required_keys if key not in schema_data]
        return {
            "is_valid": len(missing_keys) == 0,
            "missing_keys": missing_keys,
            "total_checked": len(required_keys)
        }
