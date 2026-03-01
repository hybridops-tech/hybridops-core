"""
purpose: Register built-in drivers shipped with HybridOps.Core.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from hyops.drivers.registry import DriverRegistry
from hyops.drivers.config.ansible import run as ansible_run
from hyops.drivers.config.ansible import validate_execution_schema as ansible_validate_execution_schema
from hyops.drivers.images.packer import run as packer_run
from hyops.drivers.images.packer import validate_execution_schema as packer_validate_execution_schema
from hyops.drivers.iac.terragrunt.driver import run as tg_run
from hyops.drivers.iac.terragrunt.schema import validate_execution_schema as tg_validate_execution_schema


def register_all(registry: DriverRegistry) -> None:
    registry.reserve("iac/terragrunt")
    registry.register(
        "iac/terragrunt",
        tg_run,
        source="builtin",
        execution_validator=tg_validate_execution_schema,
    )

    registry.reserve("images/packer")
    registry.register(
        "images/packer",
        packer_run,
        source="builtin",
        execution_validator=packer_validate_execution_schema,
    )

    registry.reserve("config/ansible")
    registry.register(
        "config/ansible",
        ansible_run,
        source="builtin",
        execution_validator=ansible_validate_execution_schema,
    )
