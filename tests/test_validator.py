"""Unit tests for CLI Module Validator."""

import pytest
from hybridops.cli.validator import CLIValidator

def test_validate_environment():
    validator = CLIValidator()
    res = validator.validate_environment()
    
    assert "status" in res
    assert "python_version" in res
    assert res["status"] in ["success", "failed"]

def test_validate_schema_valid():
    validator = CLIValidator()
    schema = {"name": "hybrid-core", "version": "1.0.0"}
    res = validator.validate_schema(schema, ["name", "version"])
    
    assert res["is_valid"] is True
    assert len(res["missing_keys"]) == 0

def test_validate_schema_invalid():
    validator = CLIValidator()
    schema = {"name": "hybrid-core"}
    res = validator.validate_schema(schema, ["name", "version", "environment"])
    
    assert res["is_valid"] is False
    assert "version" in res["missing_keys"]
    assert "environment" in res["missing_keys"]
