"""Tests for the repair-only IOL licence broker flow."""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hyops.blueprint.command import run_deploy
from hyops.blueprint.iol_repair import (
    IolMismatch,
    IolRepairError,
    IolRepairResult,
    SCHEMA,
    _validate_iourc,
    _verify_response,
    parse_iol_mismatch,
    prior_success_allows_repair,
    repair_iol_license,
)


class IolRepairProtocolTest(TestCase):
    def test_parses_only_structured_host_mismatch(self):
        detail = (
            "configuration apply failed: IOL licence does not match this EVE-NG host. "
            "Hostname: eve-ng-01. Host ID: 500a0232. No images were changed."
        )
        self.assertEqual(
            parse_iol_mismatch(detail),
            IolMismatch(hostname="eve-ng-01", host_id="500a0232"),
        )
        self.assertIsNone(parse_iol_mismatch("IOL licence is missing"))
        self.assertIsNone(
            parse_iol_mismatch(
                "IOL licence does not match this EVE-NG host. Hostname: eve-ng-01."
            )
        )

    def test_requires_previous_ready_output(self):
        with patch(
            "hyops.blueprint.iol_repair.read_module_state",
            return_value={"status": "error", "outputs": {"eveng_images_iol_license_ready": True}},
        ):
            self.assertTrue(prior_success_allows_repair(Path("/state"), "module#images"))
        with patch(
            "hyops.blueprint.iol_repair.read_module_state",
            return_value={"status": "error", "outputs": {}},
        ):
            self.assertFalse(prior_success_allows_repair(Path("/state"), "module#images"))

    def test_accepts_signed_short_lived_matching_response(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        nonce = "test-nonce"
        payload = {
            "schema": SCHEMA,
            "request_id": "repair-123",
            "nonce": nonce,
            "hostname": "eve-ng-01",
            "host_id": "500a0232",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            "iourc": "[license]\neve-ng-01 = 0123456789abcdef;\n",
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = base64.b64encode(private_key.sign(body)).decode("ascii")
        response = SimpleNamespace(
            status_code=200,
            content=body,
            headers={"X-HybridOps-Signature": signature},
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_key_path = root / "broker.pub.pem"
            public_key_path.write_bytes(
                public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            paths = SimpleNamespace(
                root=root,
                state_dir=root / "state",
                vault_dir=root / "vault",
            )
            ns = SimpleNamespace(
                env="repair-test",
                iol_repair_broker_url="https://repair.example.test/v1/iol",
                iol_repair_public_key=str(public_key_path),
                iol_repair_token_key="HYOPS_IOL_REPAIR_TOKEN",
                iol_repair_persist="gsm",
            )
            with (
                patch.dict(os.environ, {"HYOPS_IOL_REPAIR_TOKEN": "broker-token"}),
                patch("hyops.blueprint.iol_repair.prior_success_allows_repair", return_value=True),
                patch(
                    "hyops.blueprint.iol_repair._read_runtime_secrets",
                    return_value={"EVENG_IOL_LICENSE": "[license]\nold = abcdef0123456789;\n"},
                ),
                patch("hyops.blueprint.iol_repair._request_nonce", return_value=nonce),
                patch("hyops.blueprint.iol_repair.requests.post", return_value=response) as post,
                patch("hyops.blueprint.iol_repair._persist_iourc", return_value="gsm") as persist,
            ):
                result = repair_iol_license(
                    ns,
                    paths,
                    state_ref="platform/linux/eve-ng-images#images",
                    mismatch=IolMismatch("eve-ng-01", "500a0232"),
                )

        self.assertEqual(result.request_id, "repair-123")
        self.assertEqual(result.persisted_to, "gsm")
        persist.assert_called_once_with(
            ns,
            paths,
            "[license]\neve-ng-01 = 0123456789abcdef;\n",
        )
        request_json = post.call_args.kwargs["json"]
        self.assertTrue(request_json["previous_iol_ready"])
        self.assertEqual(request_json["hostname"], "eve-ng-01")
        self.assertNotIn("old =", json.dumps(request_json))

    def test_rejects_initial_use_before_contacting_broker(self):
        paths = SimpleNamespace(state_dir=Path("/state"))
        with (
            patch("hyops.blueprint.iol_repair.prior_success_allows_repair", return_value=False),
            patch("hyops.blueprint.iol_repair.requests.post") as post,
        ):
            with self.assertRaisesRegex(IolRepairError, "previously published"):
                repair_iol_license(
                    SimpleNamespace(),
                    paths,
                    state_ref="platform/linux/eve-ng-images#images",
                    mismatch=IolMismatch("eve-ng-01", "500a0232"),
                )
        post.assert_not_called()

    def test_rejects_repair_when_original_secret_is_absent(self):
        paths = SimpleNamespace(state_dir=Path("/state"))
        with (
            patch("hyops.blueprint.iol_repair.prior_success_allows_repair", return_value=True),
            patch("hyops.blueprint.iol_repair._read_runtime_secrets", return_value={}),
            patch("hyops.blueprint.iol_repair.requests.post") as post,
        ):
            with self.assertRaisesRegex(IolRepairError, "existing EVENG_IOL_LICENSE"):
                repair_iol_license(
                    SimpleNamespace(),
                    paths,
                    state_ref="platform/linux/eve-ng-images#images",
                    mismatch=IolMismatch("eve-ng-01", "500a0232"),
                )
        post.assert_not_called()

    def test_rejects_bad_signature_and_wrong_host_licence(self):
        private_key = Ed25519PrivateKey.generate()
        with TemporaryDirectory() as tmp:
            public_key_path = Path(tmp) / "broker.pub.pem"
            public_key_path.write_bytes(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            with self.assertRaisesRegex(IolRepairError, "signature is invalid"):
                _verify_response(
                    b"signed body",
                    base64.b64encode(private_key.sign(b"different body")).decode("ascii"),
                    public_key_path,
                )
        with self.assertRaisesRegex(IolRepairError, "different host"):
            _validate_iourc(
                "[license]\neve-ng-02 = 0123456789abcdef;\n",
                "eve-ng-01",
            )


class IolRepairDeployTest(TestCase):
    def test_exact_mismatch_repairs_and_retries_step_once(self):
        step = {
            "id": "images",
            "module_ref": "platform/linux/eve-ng-images",
            "state_instance": "images",
            "action": "apply",
            "phase": "operations",
            "optional": False,
        }
        payload = {
            "blueprint_ref": "test/eve-ng@v1",
            "mode": "hybrid",
            "path": "/tmp/blueprint.yml",
            "order": ["images"],
            "steps": [step],
            "policy": {"fail_fast": True},
        }
        ns = SimpleNamespace(
            execute=True,
            yes=True,
            json=False,
            root=None,
            env="test",
            file=None,
            skip_preflight=True,
            preflight_bypass_reason="test",
            repair_iol_license=True,
        )
        paths = SimpleNamespace(
            root=Path("/tmp/test"),
            state_dir=Path("/tmp/test/state"),
            config_dir=Path("/tmp/test/config"),
        )
        mismatch = (
            "IOL licence does not match this EVE-NG host. "
            "Hostname: eve-ng-01. Host ID: 500a0232."
        )
        repair = IolRepairResult("request-1", "eve-ng-01", "500a0232", "runtime-vault")
        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.require_runtime_writable"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch("hyops.blueprint.command._confirm_deploy_if_needed", return_value=0),
            patch("hyops.blueprint.command._automatic_lab_restore_eligible", return_value=False),
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
            patch("hyops.blueprint.command.enforce_step_contracts"),
            patch("hyops.blueprint.command._step_failure_state", return_value=("", "", "")),
            patch("hyops.blueprint.command._new_step_failure_detail", return_value=mismatch),
            patch("hyops.blueprint.command.run_step_module_command", side_effect=[1, 0]) as command,
            patch("hyops.blueprint.command.repair_iol_license", return_value=repair) as repair_call,
            patch("hyops.blueprint.command._step_presentation", return_value=("Images", "ready", "")),
            patch("hyops.blueprint.command._select_lab_restore_mode", return_value=("none", None)),
        ):
            rc = run_deploy(ns)

        self.assertEqual(rc, 0)
        self.assertEqual(command.call_count, 2)
        repair_call.assert_called_once()
