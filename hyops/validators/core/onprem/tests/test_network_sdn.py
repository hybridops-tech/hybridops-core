"""
purpose: Test core/onprem/network-sdn input validation.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.core.onprem.network_sdn import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "core" / "onprem" / "network-sdn"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    example = yaml.safe_load(
        (MODULE_ROOT / "examples" / "inputs.min.yml").read_text(encoding="utf-8")
    )
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(example)
    return inputs


class NetworkSdnValidatorTests(unittest.TestCase):
    def test_existing_zone_and_vnet_ids_pass(self) -> None:
        inputs = valid_inputs()
        self.assertEqual(inputs["zone_name"], "hybzone")
        self.assertIn("vnetmgmt", inputs["vnets"])
        validate(inputs)

    def test_shipped_examples_still_validate(self) -> None:
        spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
        for path in sorted((MODULE_ROOT / "examples").glob("*.yml")):
            with self.subTest(example=path.name):
                example = yaml.safe_load(path.read_text(encoding="utf-8"))
                inputs = deepcopy(spec["inputs"]["defaults"])
                inputs.update(example)
                validate(inputs)

    def test_one_character_zone_and_vnet_ids_fail_with_the_module_rule(self) -> None:
        zone_inputs = valid_inputs()
        zone_inputs["zone_name"] = "a"
        with self.assertRaises(ValueError) as zone_error:
            validate(zone_inputs)
        zone_message = str(zone_error.exception)
        self.assertIn("inputs.zone_name", zone_message)
        self.assertIn("2-8 characters", zone_message)
        self.assertIn("lowercase letter", zone_message)

        vnet_inputs = valid_inputs()
        vnet = vnet_inputs["vnets"].pop("vnetmgmt")
        vnet_inputs["vnets"]["a"] = vnet
        with self.assertRaises(ValueError) as vnet_error:
            validate(vnet_inputs)
        vnet_message = str(vnet_error.exception)
        self.assertIn("inputs.vnets key", vnet_message)
        self.assertIn("2-8 characters", vnet_message)
        self.assertIn("lowercase letter", vnet_message)

    def test_length_boundaries(self) -> None:
        shortest = valid_inputs()
        shortest["zone_name"] = "ab"
        vnet = shortest["vnets"].pop("vnetmgmt")
        shortest["vnets"]["cd"] = vnet
        validate(shortest)

        longest = valid_inputs()
        longest["zone_name"] = "hybzone1"
        vnet = longest["vnets"].pop("vnetmgmt")
        longest["vnets"]["vnetmgmt"] = vnet
        validate(longest)

        too_long = valid_inputs()
        too_long["zone_name"] = "hybzone12"
        with self.assertRaises(ValueError) as error:
            validate(too_long)
        self.assertIn("2-8 characters", str(error.exception))

    def test_local_subnet_key_is_not_an_sdn_id(self) -> None:
        inputs = valid_inputs()
        vnet = inputs["vnets"]["vnetmgmt"]
        subnet = vnet["subnets"].pop("submgmt")
        vnet["subnets"]["subnet_name"] = subnet
        validate(inputs)

        empty = valid_inputs()
        vnet = empty["vnets"]["vnetmgmt"]
        subnet = vnet["subnets"].pop("submgmt")
        vnet["subnets"]["   "] = subnet
        with self.assertRaises(ValueError) as error:
            validate(empty)
        self.assertIn("subnets key must be a non-empty string", str(error.exception))


if __name__ == "__main__":
    unittest.main()
