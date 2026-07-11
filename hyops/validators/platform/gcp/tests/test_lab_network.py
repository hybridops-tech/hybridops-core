"""
purpose: Test platform/gcp/lab-network input validation.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.gcp.lab_network import validate
from hyops.validators.registry import ModuleValidationError


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "gcp" / "lab-network"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    example = yaml.safe_load(
        (MODULE_ROOT / "examples" / "inputs.min.yml").read_text(encoding="utf-8")
    )
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(example)
    return inputs


class LabNetworkValidatorTests(unittest.TestCase):
    def test_minimal_example_is_valid(self) -> None:
        validate(valid_inputs())

    def test_invalid_inputs_are_rejected(self) -> None:
        cases = {
            "placeholder region": ("region", "CHANGE_ME_GCP_REGION"),
            "invalid project": ("project_id", "Not_A_Project"),
            "invalid network name": ("network_name", "Lab_Network"),
            "host address cidr": ("subnetwork_cidr", "10.80.0.1/24"),
            "public cidr": ("subnetwork_cidr", "8.8.8.0/24"),
            "empty iap ranges": ("iap_source_cidrs", []),
            "ipv6 iap range": ("iap_source_cidrs", ["2001:db8::/32"]),
            "empty iap tags": ("iap_target_tags", []),
            "small nat port allocation": ("nat_min_ports_per_vm", 16),
            "invalid nat log filter": ("nat_log_filter", "VERBOSE"),
        }

        for label, (key, value) in cases.items():
            with self.subTest(label=label):
                inputs = valid_inputs()
                inputs[key] = value
                with self.assertRaises(ModuleValidationError):
                    validate(inputs)

    def test_region_may_come_from_gcp_init(self) -> None:
        inputs = valid_inputs()
        inputs["region"] = ""
        validate(inputs)

    def test_iap_lists_are_optional_when_iap_is_disabled(self) -> None:
        inputs = valid_inputs()
        inputs["enable_iap_ssh"] = False
        inputs["iap_source_cidrs"] = []
        inputs["iap_target_tags"] = []
        validate(inputs)


if __name__ == "__main__":
    unittest.main()
