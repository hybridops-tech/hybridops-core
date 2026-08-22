# `hyops/diagnostics/environment.py`

```python
"""Execution environment diagnostics.

This module provides small, read-only helpers for inspecting the environment
in which HybridOps Core is currently running.

The diagnostics intentionally use only Python's standard library so that they
can be used during early troubleshooting without requiring additional
dependencies.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EnvironmentDiagnostics:
    """Describe the basic environment of the current HybridOps process.

    Attributes:
        python_version: Full Python version string reported by the interpreter.
        python_major: Python major version number.
        python_minor: Python minor version number.
        python_implementation: Python implementation name, such as CPython.
        operating_system: Operating-system name reported by ``platform.system``.
        operating_system_release: Operating-system release string.
        architecture: Process architecture, such as ``64bit``.
        machine: Hardware platform identifier.
        working_directory: Current process working directory.
        working_directory_exists: Whether the working directory exists.
        executable: Absolute path to the Python executable.
    """

    python_version: str
    python_major: int
    python_minor: int
    python_implementation: str
    operating_system: str
    operating_system_release: str
    architecture: str
    machine: str
    working_directory: str
    working_directory_exists: bool
    executable: str

    @property
    def is_supported_python(self) -> bool:
        """Return whether the running Python version meets Core's requirement.

        HybridOps Core currently requires Python 3.11 or newer.
        """

        return (self.python_major, self.python_minor) >= (3, 11)

    def to_dict(self) -> dict[str, Any]:
        """Return the diagnostics as a serialisable dictionary.

        The computed ``is_supported_python`` value is included because it is
        useful to callers that want to report whether the current interpreter
        satisfies the Core runtime requirement.
        """

        result = asdict(self)
        result["is_supported_python"] = self.is_supported_python
        return result


def collect_environment_diagnostics() -> EnvironmentDiagnostics:
    """Collect read-only diagnostics for the current process.

    Returns:
        An :class:`EnvironmentDiagnostics` instance containing information
        about the current Python interpreter, operating system, process
        architecture, and working directory.
    """

    working_directory = Path.cwd()

    return EnvironmentDiagnostics(
        python_version=platform.python_version(),
        python_major=sys.version_info.major,
        python_minor=sys.version_info.minor,
        python_implementation=platform.python_implementation(),
        operating_system=platform.system(),
        operating_system_release=platform.release(),
        architecture=platform.architecture()[0],
        machine=platform.machine(),
        working_directory=str(working_directory),
        working_directory_exists=working_directory.exists(),
        executable=os.path.abspath(sys.executable),
    )
```
