"""Tests for the HybridOps module specification contract validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "tools" / "ci" / "check-module-contracts.py"


def _load_validator() -> Any:
    """Load the CI validator module whose filename contains hyphens."""
    spec = importlib.util.spec_from_file_location(
        "check_module_contracts",
        VALIDATOR_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load validator: {VALIDATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def valid_spec() -> dict[str, Any]:
    """Return a minimal valid HybridOps ModuleSpec."""
    return {
        "api_version": "hybridops/v1",
        "kind": "ModuleSpec",
        "module_ref": "examples/test/sample",
        "metadata": {
            "title": "Sample Module",
            "description": "A module used for contract validation tests.",
        },
        "requirements": {
            "credentials": [],
        },
        "inputs": {
            "defaults": {
                "message": "hello",
            },
        },
        "execution": {
            "driver": "iac/terragrunt",
            "profile": "local@v1.0",
            "pack_ref": {
                "id": "sample-pack",
            },
        },
        "outputs": {
            "publish": [],
            "probes": [],
        },
        "constraints": [],
    }


def write_spec(
    tmp_path: Path,
    data: dict[str, Any],
) -> tuple[Path, Path]:
    """Write a module fixture using the repository's module directory layout."""
    module_dir = tmp_path / "modules" / "examples" / "test" / "sample"
    module_dir.mkdir(parents=True)

    spec_path = module_dir / "spec.yml"
    spec_path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )

    return tmp_path, spec_path


def test_valid_module_spec_has_no_failures(tmp_path: Path) -> None:
    """A complete ModuleSpec should pass validation."""
    repo_root, spec_path = write_spec(tmp_path, valid_spec())

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert failures == []


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (
            "api_version",
            "hybridops/v2",
            "api_version must be 'hybridops/v1'",
        ),
        (
            "kind",
            "WrongKind",
            "kind must be 'ModuleSpec'",
        ),
        (
            "module_ref",
            "examples/test/wrong",
            "module_ref 'examples/test/wrong' does not match",
        ),
    ],
)
def test_invalid_top_level_contract_fields(
    tmp_path: Path,
    field: str,
    value: str,
    expected: str,
) -> None:
    """Invalid top-level contract values should be reported."""
    data = valid_spec()
    data[field] = value

    repo_root, spec_path = write_spec(tmp_path, data)

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert any(expected in failure for failure in failures)


@pytest.mark.parametrize(
    ("section", "value", "expected"),
    [
        (
            "metadata",
            None,
            "metadata: expected a mapping",
        ),
        (
            "requirements",
            None,
            "requirements: expected a mapping",
        ),
        (
            "inputs",
            None,
            "inputs: expected a mapping",
        ),
        (
            "execution",
            None,
            "execution: expected a mapping",
        ),
        (
            "outputs",
            None,
            "outputs: expected a mapping",
        ),
        (
            "constraints",
            None,
            "constraints: expected a list",
        ),
    ],
)
def test_missing_required_sections_are_reported(
    tmp_path: Path,
    section: str,
    value: Any,
    expected: str,
) -> None:
    """Missing required contract sections should fail validation."""
    data = valid_spec()
    data.pop(section)

    if value is not None:
        data[section] = value

    repo_root, spec_path = write_spec(tmp_path, data)

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert any(expected in failure for failure in failures)


def test_inputs_defaults_must_be_a_mapping(tmp_path: Path) -> None:
    """inputs.defaults must contain a mapping of default values."""
    data = valid_spec()
    data["inputs"]["defaults"] = []

    repo_root, spec_path = write_spec(tmp_path, data)

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert any(
        "inputs.defaults: expected a mapping" in failure
        for failure in failures
    )


def test_execution_requires_driver_profile_and_pack_id(
    tmp_path: Path,
) -> None:
    """Execution must identify the driver, profile, and implementation pack."""
    data = valid_spec()
    data["execution"] = {
        "driver": "",
        "profile": "",
        "pack_ref": {},
    }

    repo_root, spec_path = write_spec(tmp_path, data)

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert any(
        "execution.driver must be a non-empty string" in failure
        for failure in failures
    )
    assert any(
        "execution.profile must be a non-empty string" in failure
        for failure in failures
    )
    assert any(
        "execution.pack_ref.id must be a non-empty string" in failure
        for failure in failures
    )


def test_output_contract_requires_lists(tmp_path: Path) -> None:
    """outputs.publish and outputs.probes must both be lists."""
    data = valid_spec()
    data["outputs"] = {
        "publish": {},
        "probes": {},
    }

    repo_root, spec_path = write_spec(tmp_path, data)

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert any(
        "outputs.publish: expected a list" in failure
        for failure in failures
    )
    assert any(
        "outputs.probes: expected a list" in failure
        for failure in failures
    )


def test_multiple_contract_errors_are_reported_together(
    tmp_path: Path,
) -> None:
    """The validator should report multiple errors instead of stopping early."""
    data = valid_spec()
    data["api_version"] = "invalid"
    data["kind"] = "InvalidKind"
    data["execution"] = {}
    data["constraints"] = {}

    repo_root, spec_path = write_spec(tmp_path, data)

    failures = validator.validate_module_spec(spec_path, repo_root)

    assert len(failures) >= 4
    assert any("api_version" in failure for failure in failures)
    assert any("kind" in failure for failure in failures)
    assert any("execution.driver" in failure for failure in failures)
    assert any("constraints" in failure for failure in failures)


def test_check_module_contracts_finds_all_specs(
    tmp_path: Path,
) -> None:
    """Repository-level validation should inspect every discovered spec."""
    repo_root = tmp_path

    valid_dir = repo_root / "modules" / "examples" / "test" / "valid"
    invalid_dir = repo_root / "modules" / "examples" / "test" / "invalid"

    valid_dir.mkdir(parents=True)
    invalid_dir.mkdir(parents=True)

    valid_data = valid_spec()
    valid_data["module_ref"] = "examples/test/valid"

    invalid_data = valid_spec()
    invalid_data["module_ref"] = "examples/test/invalid"
    invalid_data["kind"] = "InvalidKind"

    (valid_dir / "spec.yml").write_text(
        yaml.safe_dump(valid_data, sort_keys=False),
        encoding="utf-8",
    )

    (invalid_dir / "spec.yml").write_text(
        yaml.safe_dump(invalid_data, sort_keys=False),
        encoding="utf-8",
    )

    failures, module_count = validator.check_module_contracts(repo_root)

    assert module_count == 2
    assert any("kind must be 'ModuleSpec'" in failure for failure in failures)
