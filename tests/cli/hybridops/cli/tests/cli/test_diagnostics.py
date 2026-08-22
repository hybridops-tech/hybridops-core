"""
Unit tests for hybridops.cli.diagnostics module.
"""

import os
import sys
from unittest.mock import patch

import pytest

from hybridops.cli.diagnostics import (
    CheckResult,
    CheckStatus,
    DiagnosticReport,
    EnvironmentDiagnosticsRunner,
)


def test_diagnostic_report_health_properties() -> None:
    """Test aggregated status calculation in DiagnosticReport."""
    report = DiagnosticReport(
        results=[
            CheckResult("Check 1", CheckStatus.PASS, "OK"),
            CheckResult("Check 2", CheckStatus.WARN, "Warning"),
        ]
    )
    assert report.is_healthy is True
    assert report.has_warnings is True

    report.results.append(CheckResult("Check 3", CheckStatus.FAIL, "Failed"))
    assert report.is_healthy is False


def test_check_python_version_pass() -> None:
    """Verify check passes on modern Python runtime."""
    runner = EnvironmentDiagnosticsRunner()
    with patch.object(sys, "version_info", (3, 11, 2, "final", 0)):
        result = runner.check_python_version()
        assert result.status == CheckStatus.PASS
        assert "satisfies requirement" in result.message


def test_check_python_version_fail() -> None:
    """Verify check fails on legacy Python runtime."""
    runner = EnvironmentDiagnosticsRunner()
    with patch.object(sys, "version_info", (3, 10, 8, "final", 0)):
        result = runner.check_python_version()
        assert result.status == CheckStatus.FAIL
        assert "unsupported" in result.message


def test_check_cli_dependencies_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test binary discovery with simulated missing and present executables."""
    runner = EnvironmentDiagnosticsRunner()

    def mock_which(cmd: str) -> str | None:
        if cmd == "git":
            return "/usr/bin/git"
        return None

    monkeypatch.setattr("shutil.which", mock_which)
    results = runner.check_cli_dependencies()

    git_check = next(r for r in results if r.name == "Binary: git")
    assert git_check.status == CheckStatus.PASS
    assert git_check.details == "Path: /usr/bin/git"

    docker_check = next(r for r in results if r.name == "Binary: docker")
    assert docker_check.status == CheckStatus.WARN


def test_check_workdir_permissions_success(tmp_path: pytest.TempPathFactory) -> None:
    """Test workspace check on a valid, writable temp directory."""
    runner = EnvironmentDiagnosticsRunner(workdir=str(tmp_path))
    result = runner.check_workdir_permissions()
    assert result.status == CheckStatus.PASS


def test_check_workdir_permissions_nonexistent() -> None:
    """Test workspace check on a non-existent path."""
    runner = EnvironmentDiagnosticsRunner(workdir="/invalid/path/that/does/not/exist")
    result = runner.check_workdir_permissions()
    assert result.status == CheckStatus.FAIL
    assert "does not exist" in result.message


def test_run_all_checks_integration(tmp_path: pytest.TempPathFactory) -> None:
    """Test full execution runner pipeline."""
    runner = EnvironmentDiagnosticsRunner(workdir=str(tmp_path))
    report = runner.run_all_checks()
    
    assert isinstance(report, DiagnosticReport)
    assert len(report.results) >= 5  # Python + 3 binaries + Workdir
