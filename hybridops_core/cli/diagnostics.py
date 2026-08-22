"""
Diagnostic utility for validating execution environment health in HybridOps Core.

This module provides checks for essential runtime tools, system permissions,
and environment setups to prevent downstream orchestration failures.
"""

import os
import shutil
import sys
from typing import Dict, List, NamedTuple, Optional


class CheckResult(NamedTuple):
    """Represents the outcome of an individual environment check."""
    name: str
    passed: bool
    details: str


class EnvironmentDiagnostics:
    """Encapsulates system and runtime environment validation routines."""

    REQUIRED_BINARIES: List[str] = ["git", "docker"]
    MIN_PYTHON_VERSION: tuple = (3, 8)

    @classmethod
    def check_python_version(cls) -> CheckResult:
        """Validates that the active Python version meets minimum requirements."""
        current_version = sys.version_info[:2]
        passed = current_version >= cls.MIN_PYTHON_VERSION
        version_str = f"{current_version[0]}.{current_version[1]}"
        required_str = f"{cls.MIN_PYTHON_VERSION[0]}.{cls.MIN_PYTHON_VERSION[1]}"
        
        details = (
            f"Python {version_str} detected (Minimum required: {required_str})"
            if passed
            else f"Python {version_str} is unsupported. Requires >= {required_str}"
        )
        return CheckResult("Python Version", passed, details)

    @classmethod
    def check_binary_dependencies(cls) -> List[CheckResult]:
        """Checks for the existence of required CLI tools on system PATH."""
        results: List[CheckResult] = []
        for binary in cls.REQUIRED_BINARIES:
            binary_path = shutil.which(binary)
            passed = binary_path is not None
            details = (
                f"Found at {binary_path}"
                if passed
                else f"Executable '{binary}' not found on PATH"
            )
            results.append(CheckResult(f"Binary: {binary}", passed, details))
        return results

    @classmethod
    def check_directory_permissions(cls, target_dir: Optional[str] = None) -> CheckResult:
        """Verifies read and write permissions for working directory or target path."""
        path_to_check = target_dir or os.getcwd()
        writable = os.access(path_to_check, os.W_OK)
        readable = os.access(path_to_check, os.R_OK)
        passed = writable and readable
        
        details = f"Path '{path_to_check}' - Read: {readable}, Write: {writable}"
        return CheckResult("Directory Permissions", passed, details)

    @classmethod
    def run_all_checks(cls) -> Dict[str, List[CheckResult]]:
        """Executes all environmental diagnostic routines."""
        results: List[CheckResult] = [
            cls.check_python_version(),
            cls.check_directory_permissions(),
        ]
        results.extend(cls.check_binary_dependencies())
        
        all_passed = all(check.passed for check in results)
        return {
            "status": "HEALTHY" if all_passed else "UNHEALTHY",
            "checks": results,
        }


def run_diagnostics_cli() -> int:
    """CLI entry point for executing hybridops doctor diagnostics."""
    print("=== HybridOps Core Environment Diagnostics ===")
    diagnostic_report = EnvironmentDiagnostics.run_all_checks()
    
    for check in diagnostic_report["checks"]:
        status_symbol = "[OK]" if check.passed else "[FAIL]"
        print(f"{status_symbol} {check.name}: {check.details}")

    print("----------------------------------------------")
    print(f"Overall Environment Status: {diagnostic_report['status']}")
    
    return 0 if diagnostic_report["status"] == "HEALTHY" else 1


if __name__ == "__main__":
    sys.exit(run_diagnostics_cli())
