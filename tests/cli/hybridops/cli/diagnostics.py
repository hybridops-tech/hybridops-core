**File Path:** `hybridops/cli/diagnostics.py`

```python
"""
HybridOps Core - Environment Diagnostics Module.

Provides preflight diagnostic checks for the host execution environment,
verifying Python runtimes, required CLI binaries, and filesystem health.
"""

from dataclasses import dataclass, field
from enum import Enum
import os
import shutil
import sys
from typing import Dict, List, Optional


class CheckStatus(Enum):
    """Status result of an individual diagnostic check."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    """Represents the outcome of a single environment check."""
    name: str
    status: CheckStatus
    message: str
    details: Optional[str] = None


@dataclass
class DiagnosticReport:
    """Aggregated summary of all executed diagnostic checks."""
    results: List[CheckResult] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        """Return True if no checks resulted in FAIL."""
        return not any(res.status == CheckStatus.FAIL for res in self.results)

    @property
    def has_warnings(self) -> bool:
        """Return True if any check resulted in WARN."""
        return any(res.status == CheckStatus.WARN for res in self.results)


class EnvironmentDiagnosticsRunner:
    """Runner for inspecting the local host environment against HybridOps dependencies."""

    MIN_PYTHON_VERSION = (3, 11)
    RECOMMENDED_BINARIES = ["git", "ansible-playbook", "docker"]

    def __init__(self, workdir: Optional[str] = None) -> None:
        self.workdir = workdir or os.getcwd()

    def check_python_version(self) -> CheckResult:
        """Verify that the current Python interpreter satisfies minimum requirements (>= 3.11)."""
        current_ver = sys.version_info[:2]
        version_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        if current_ver >= self.MIN_PYTHON_VERSION:
            return CheckResult(
                name="Python Runtime",
                status=CheckStatus.PASS,
                message=f"Python version {version_str} satisfies requirement (>= 3.11)."
            )
        return CheckResult(
            name="Python Runtime",
            status=CheckStatus.FAIL,
            message=f"Python version {version_str} is unsupported. HybridOps requires Python >= 3.11."
        )

    def check_cli_dependencies(self) -> List[CheckResult]:
        """Check for the presence of recommended CLI binaries on system PATH."""
        results: List[CheckResult] = []
        for binary in self.RECOMMENDED_BINARIES:
            binary_path = shutil.which(binary)
            if binary_path:
                results.append(
                    CheckResult(
                        name=f"Binary: {binary}",
                        status=CheckStatus.PASS,
                        message=f"Found '{binary}' executable.",
                        details=f"Path: {binary_path}"
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=f"Binary: {binary}",
                        status=CheckStatus.WARN,
                        message=f"Binary '{binary}' was not found on PATH. Some module packs may require it."
                    )
                )
        return results

    def check_workdir_permissions(self) -> CheckResult:
        """Verify that the designated workspace directory exists and is writable."""
        if not os.path.exists(self.workdir):
            return CheckResult(
                name="Workspace Directory",
                status=CheckStatus.FAIL,
                message=f"Directory '{self.workdir}' does not exist."
            )

        if os.access(self.workdir, os.W_OK):
            return CheckResult(
                name="Workspace Directory",
                status=CheckStatus.PASS,
                message=f"Workspace '{self.workdir}' is accessible and writable."
            )

        return CheckResult(
            name="Workspace Directory",
            status=CheckStatus.FAIL,
            message=f"Workspace '{self.workdir}' exists but is not writable."
        )

    def run_all_checks(self) -> DiagnosticReport:
        """Execute all environment diagnostics and return an aggregated report."""
        report = DiagnosticReport()
        report.results.append(self.check_python_version())
        report.results.extend(self.check_cli_dependencies())
        report.results.append(self.check_workdir_permissions())
        return report
