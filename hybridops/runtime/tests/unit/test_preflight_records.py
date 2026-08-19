import pytest
from pathlib import Path
from hybridops.runtime.preflight import validate_run_record_path, RunRecordValidationError


def test_validate_run_record_path_success(tmp_path: Path):
    """Verifies that a valid writable directory resolves successfully."""
    log_dir = tmp_path / "logs"
    result = validate_run_record_path(log_dir)
    
    assert result.exists()
    assert result.is_dir()
    assert result == log_dir.resolve()


def test_validate_run_record_path_creates_missing(tmp_path: Path):
    """Verifies auto-creation of missing parent directories."""
    nested_dir = tmp_path / "nested" / "hybridops" / "logs"
    assert not nested_dir.exists()

    result = validate_run_record_path(nested_dir, create_if_missing=True)
    assert result.exists()


def test_validate_run_record_path_fails_when_path_is_file(tmp_path: Path):
    """Verifies error handling when path exists as a regular file."""
    file_path = tmp_path / "regular_file.txt"
    file_path.touch()

    with pytest.raises(RunRecordValidationError, match="exists but is a file"):
        validate_run_record_path(file_path)


def test_validate_run_record_path_unwritable(tmp_path: Path, monkeypatch):
    """Verifies failure response when directory lacks write permissions."""
    read_only_dir = tmp_path / "readonly_logs"
    read_only_dir.mkdir()
    read_only_dir.chmod(0o444)  # Read-only permissions

    try:
        with pytest.raises(RunRecordValidationError, match="Permission denied|not writable"):
            validate_run_record_path(read_only_dir)
    finally:
        # Restore permissions for test cleanup
        read_only_dir.chmod(0o755)
