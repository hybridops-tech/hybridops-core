import pytest
from hybridops.core.schema import (
    validate_blueprint_contract,
    BlueprintSchemaValidationError,
)
def test_valid_blueprint_schema():
    """Verifies successful validation of a complete blueprint manifest."""
    valid_manifest = {
        "apiVersion": "hybridops.tech/v1",
        "kind": "Blueprint",
        "metadata": {"name": "authoritative-foundation"},
        "spec": {"modules": []},
    }
    assert validate_blueprint_contract(valid_manifest) is True
def test_missing_required_keys():
    """Verifies failure when required top-level keys are missing."""
    invalid_manifest = {
        "apiVersion": "hybridops.tech/v1",
        "kind": "Blueprint",
    }
    with pytest.raises(BlueprintSchemaValidationError, match="missing required top-level key"):
        validate_blueprint_contract(invalid_manifest)
def test_invalid_kind():
    """Verifies failure when kind is not 'Blueprint'."""
    invalid_manifest = {
        "apiVersion": "hybridops.tech/v1",
        "kind": "Deployment",
        "metadata": {"name": "invalid-kind-test"},
        "spec": {},
    }
    with pytest.raises(BlueprintSchemaValidationError, match="Invalid blueprint kind"):
        validate_blueprint_contract(invalid_manifest)
def test_unsupported_api_version():
    """Verifies failure when an unsupported apiVersion is supplied."""
    invalid_manifest = {
        "apiVersion": "hybridops.tech/v0beta",
        "kind": "Blueprint",
        "metadata": {"name": "invalid-version-test"},
        "spec": {},
    }
    with pytest.raises(BlueprintSchemaValidationError, match="Unsupported apiVersion"):
        validate_blueprint_contract(invalid_manifest)
def test_invalid_metadata_name():
    """Verifies failure when metadata name is missing or empty."""
    invalid_manifest = {
        "apiVersion": "hybridops.tech/v1",
        "kind": "Blueprint",
        "metadata": {"name": ""},
        "spec": {},
    }
    with pytest.raises(BlueprintSchemaValidationError, match="non-empty 'name' field"):
        validate_blueprint_contract(invalid_manifest)