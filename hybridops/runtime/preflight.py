import os
import sys
from pathlib import Path
from typing import Optional, Union


class RunRecordValidationError(Exception):
    """Raised when the runtime log or execution-record directory is invalid or unwritable."""
    pass


def validate_run_record_path(
    path: Optional[Union[str, Path]] = None,
    create_if_missing: bool = True
) -> Path:
    """
    Validates that the output directory for run records exists and is writable.

    :param path: Custom log directory path. Defaults to ~/.hybridops/logs
    :param create_if_missing: Automatically attempt to create directory structure if absent.
    :return: Resolved Path object for the target log directory.
    :raises RunRecordValidationError: If the path is unwritable or cannot be created.
    """
    if path is None:
        target_path = Path.home() / ".hybridops" / "logs"
    else:
        target_path = Path(path).expanduser().resolve()

    # Attempt directory creation if missing
    if not target_path.exists():
        if not create_if_missing:
            raise RunRecordValidationError(
                f"Run-record path '{target_path}' does not exist and auto-creation is disabled."
            )
        try:
            target_path.mkdir(parents=True, exist_ok=True)
        except PermissionError as err:
            raise RunRecordValidationError(
                f"Permission denied: Unable to create run-record directory at '{target_path}'."
            ) from err
        except OSError as err:
            raise RunRecordValidationError(
                f"Failed to create run-record directory '{target_path}': {err}"
            ) from err

    # Verify that target is a directory
    if not target_path.is_dir():
        raise RunRecordValidationError(
            f"Run-record path '{target_path}' exists but is a file, not a directory."
        )

    # Verify write permissions using os.access and direct probe file check
    if not os.access(target_path, os.W_OK):
        raise RunRecordValidationError(
            f"Permission denied: Run-record directory '{target_path}' is not writable."
        )

    probe_file = target_path / f".write_probe_{os.getpid()}"
    try:
        probe_file.touch(exist_ok=True)
        probe_file.unlink(missing_ok=True)
    except (PermissionError, OSError) as err:
        raise RunRecordValidationError(
            f"Preflight write check failed for run-record path '{target_path}': {err}"
        ) from err

    return target_path


def run_preflight_checks(log_dir: Optional[Union[str, Path]] = None) -> None:
    """
    Entrypoint executed prior to contract execution. 
    Halts execution cleanly if environment preflight fails.
    """
    try:
        resolved_path = validate_run_record_path(log_dir)
    except RunRecordValidationError as error:
        sys.stderr.write(f"[HYOPS PREFLIGHT ERROR] {error}\n")
        sys.exit(1)
