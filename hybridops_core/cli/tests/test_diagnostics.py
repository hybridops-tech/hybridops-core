"""
Unit tests for the HybridOps Core diagnostic utility module.
"""

import sys
from unittest.mock import MagicMock, patch
import pytest

from hybridops.cli.diagnostics import (
    CheckResult,
    EnvironmentDiagnostics,
    run_diagnostics_cli,
)


def test_check_python_version_pass():
    """Verify python version check passes when requirement is met."""
    with patch.object(sys, "version_info", (3, 10, 0, "final", 0)):
        result = EnvironmentDiagnostics.check_python_version()
        assert result.passed is True
        assert "Python 3.10 detected" in result.details


def test_check_python_version_fail():
    """Verify python version check fails when requirement is not met."""
    with patch.object(sys, "version_info", (3, 6, 0, "final", 0)):
        result = EnvironmentDiagnostics.check_python_version()
        assert result.passed is False
        assert "unsupported" in result.details


def test_check_binary_dependencies_found(monkeypatch):
    """Verify binary dependency check passes when binaries are present on PATH."""
    def mock_which(binary_name):
        return f"/usr/bin/{binary_name}"

    monkeypatch.setattr("shutil.which", mock_which)
    results = EnvironmentDiagnostics.check_binary_dependencies()

    assert len(results) == len(EnvironmentDiagnostics.REQUIRED_BINARIES)
    for res in results:
        assert res.passed is True
        assert "Found at /usr/bin/" in res.details


def test_check_binary_dependencies_missing(monkeypatch):
    """Verify binary dependency check fails when binary is missing from PATH."""
    monkeypatch.setattr("shutil.which", lambda x: None)
    results = EnvironmentDiagnostics.check_binary_dependencies()

    for res in results:
        assert res.passed is False
        assert "not found on PATH" in res.details


def test_check_directory_permissions_success(tmp_path):
    """Verify directory permission check succeeds on writable temporary directory."""
    result = EnvironmentDiagnostics.check_directory_permissions(target_dir=str(tmp_path))
    assert result.passed is True
    assert "Read: True, Write: True" in result.details


def test_run_all_checks_healthy(monkeypatch, tmp_path):
    """Verify run_all_checks returns HEALTHY when all sub-checks pass."""
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    report = EnvironmentDiagnostics.run_all_checks(target_dir=str(tmp_path))

    assert report["status"] == "HEALTHY"
    assert len(report["checks"]) >= 3


def test_run_diagnostics_cli_exit_code_success(monkeypatch, capsys):
    """Verify CLI returns exit code 0 when environment is healthy."""
    monkeypatch.setattr(
        EnvironmentDiagnostics,
        "run_all_checks",
        lambda: {
            "status": "HEALTHY",
            "checks": [CheckResult("Mock Check", True, "Mock passed details")],
        },
    )
    exit_code = run_diagnostics_cli()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[OK] Mock Check: Mock passed details" in captured.out
    assert "Overall Environment Status: HEALTHY" in captured.out


def test_run_diagnostics_cli_exit_code_failure(monkeypatch, capsys):
    """Verify CLI returns exit code 1 when environment is unhealthy."""
    monkeypatch.setattr(
        EnvironmentDiagnostics,
        "run_all_checks",
        lambda: {
            "status": "UNHEALTHY",
            "checks": [CheckResult("Mock Check", False, "Mock failure details")],
        },
    )
    exit_code = run_diagnostics_cli()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[FAIL] Mock Check: Mock failure details" in captured.out
    assert "Overall Environment Status: UNHEALTHY" in captured.out
