import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import yaml

from hyops.blueprint.contracts import resolved_step_inputs_file
from hyops.blueprint.schema import load_blueprint, validate_blueprint


class BlueprintStepContractTest(TestCase):
    def spec(self, **step_fields):
        return {
            "api_version": "hybridops/v1",
            "kind": "BlueprintSpec",
            "blueprint_ref": "test/step-contract@v1",
            "steps": [{
                "id": "shared_control_host",
                "module_ref": "org/hetzner/shared-control-host",
                **step_fields,
            }],
        }

    def test_rejects_misplaced_input_and_names_the_step(self):
        spec = self.spec(inputs={}, firewall_name="example-firewall")
        with self.assertRaisesRegex(
            ValueError,
            r"steps\[1\].*shared_control_host.*unknown keys: firewall_name",
        ):
            validate_blueprint(spec, Path("blueprint.yml"))

    def test_reports_all_unknown_keys_in_stable_order(self):
        spec = self.spec(z_option=True, a_option=False, inputs={})
        with self.assertRaisesRegex(
            ValueError,
            r"steps\[1\].*shared_control_host.*unknown keys: a_option, z_option",
        ):
            validate_blueprint(spec, Path("blueprint.yml"))

    def test_preserves_module_specific_inputs_and_supported_step_fields(self):
        inputs = {"firewall_name": "example-firewall", "custom": {"option": 3}}
        spec = self.spec(
            inputs=inputs,
            inputs_file="host-inputs.yml",
            execution_profile="default",
            state_instance="control_host",
            action="validate",
            phase="operations",
            requires=[],
            with_deps=True,
            skip_if_state_ok=True,
            verify_state_on_skip=True,
            retain_on_destroy=False,
            destroy_gate=False,
            destroy_subsumed_by=None,
            optional=True,
            presentation={"label": "Control host"},
            contracts={"addressing_mode": "static"},
        )
        step = validate_blueprint(spec, Path("blueprint.yml"))["steps"][0]
        self.assertEqual(step["inputs"], inputs)
        self.assertEqual(step["inputs_file"], "host-inputs.yml")
        self.assertEqual(step["presentation"], {"label": "Control host"})
        self.assertTrue(step["optional"])
        self.assertTrue(step["verify_state_on_skip"])

    def test_shipped_control_host_retains_firewall_inputs(self):
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints/networking/edge-control-plane@v1/blueprint.yml"
        validated = validate_blueprint(load_blueprint(path), path)
        step = next(s for s in validated["steps"] if s["id"] == "shared_control_host")
        inputs = step["inputs"]
        self.assertEqual(inputs.get("firewall_name"), "CHANGE_ME_CONTROL_FIREWALL_NAME")
        self.assertEqual(inputs.get("ssh_source_cidrs"), ["CHANGE_ME_OPERATOR_CIDR"])
        self.assertEqual(inputs.get("firewall_extra_tcp_ports"), [80, 443])

    def test_materialized_inputs_resolve_controller_user_token(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = {
                "blueprint_ref": "test/step-contract@v1",
                "path": str(root / "blueprint.yml"),
            }
            step = {
                "id": "local_step",
                "inputs": {
                    "operator": "${USER}",
                    "paths": ["/srv/${USER}/lab", "$HOME/remains-literal"],
                },
            }
            paths = SimpleNamespace(work_dir=root / "work")

            with patch.dict(os.environ, {"USER": "operator"}, clear=True):
                inputs_file = resolved_step_inputs_file(step, payload, paths)

            materialized = yaml.safe_load(inputs_file.read_text(encoding="utf-8"))
            self.assertEqual(materialized["operator"], "operator")
            self.assertEqual(materialized["paths"][0], "/srv/operator/lab")
            self.assertEqual(materialized["paths"][1], "$HOME/remains-literal")
