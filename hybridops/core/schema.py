"""
HybridOps Core Schema Validation Module
Provides preflight contract schema checks for blueprint manifests.
"""
from typing import Any, Dict, List, Optional
class BlueprintSchemaValidationError(Exception):
    """Raised when a blueprint manifest fails structural or schema validation."""
    pass
SUPPORTED_API_VERSIONS: List[str] = ["hybridops.tech/v1alpha1", "hybridops.tech/v1"]
def validate_blueprint_contract(manifest: Dict[str, Any]) -> bool:
    """
    Validates the structure and required schema properties of a blueprint manifest.
    :param manifest: Dictionary representation of blueprint parsed from YAML/JSON.
    :return: True if schema is valid.
    :raises BlueprintSchemaValidationError: If schema requirements are violated.
    """
    if not isinstance(manifest, dict):
        raise BlueprintSchemaValidationError(
            f"Expected blueprint manifest to be a dictionary, got {type(manifest).__name__}."
        )
    # Check required top-level keys
    required_keys = ["apiVersion", "kind", "metadata", "spec"]
    missing_keys = [key for key in required_keys if key not in manifest]
    if missing_keys:
        raise BlueprintSchemaValidationError(
            f"Blueprint contract missing required top-level key(s): {', '.join(missing_keys)}"
        )
    # Validate kind definition
    if manifest["kind"] != "Blueprint":
        raise BlueprintSchemaValidationError(
            f"Invalid blueprint kind '{manifest['kind']}'. Expected 'Blueprint'."
        )
    # Validate API version support
    api_version = manifest["apiVersion"]
    if api_version not in SUPPORTED_API_VERSIONS:
        raise BlueprintSchemaValidationError(
            f"Unsupported apiVersion '{api_version}'. Supported versions: {', '.join(SUPPORTED_API_VERSIONS)}"
        )
    # Validate metadata
    metadata = manifest.get("metadata", {})
    if not isinstance(metadata, dict) or "name" not in metadata or not metadata["name"]:
        raise BlueprintSchemaValidationError(
            "Blueprint metadata must contain a non-empty 'name' field."
        )
    # Validate spec section
    spec = manifest.get("spec", {})
    if not isinstance(spec, dict):
        raise BlueprintSchemaValidationError("Blueprint 'spec' block must be a valid mapping object.")
    return True
