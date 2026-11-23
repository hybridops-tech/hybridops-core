"""Tests for blueprint preflight bypass governance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.authority import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityIntervalReceipt,
    AuthorityProviderIdentity,
    AuthorityReceipt,
    AuthorityRequirement,
    AuthoritySession,
)
from hyops.blueprint.command import _successful_deploy_actions, run_deploy
from hyops.runner.command import _remote_blueprint_command
from hyops.runtime.exitcodes import CANCELLED, OPERATOR_ERROR
from hyops.runtime.paths import RuntimePaths

_PROVIDER_IDENTITY = AuthorityProviderIdentity(
    source="direct",
    distribution="hybridops-core",
    version="0.1.6",
    entry_point="test:fixture",
)


def _payload() -> dict:
    return {
        "blueprint_ref": "test/lab@v1",
        "mode": "hybrid",
        "path": "/tmp/blueprint.yml",
        "order": ["host"],
        "steps": [
            {
                "id": "host",
                "module_ref": "platform/test/host",
                "state_instance": "host",
                "action": "deploy",
                "phase": "platform",
                "optional": False,
                "with_deps": False,
            }
        ],
        "policy": {"fail_fast": True},
    }


def _namespace(
    root: Path,
    *,
    skip_preflight: bool = True,
    reason: str | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        execute=True,
        json=False,
        yes=True,
        root=str(root),
        env=None,
        ref="test/lab@v1",
        file="",
        blueprints_root="blueprints",
        module_root="modules",
        out_dir=None,
        deps_inputs_dir=None,
        deps_force=False,
        skip_preflight=skip_preflight,
        preflight_bypass_reason=reason,
        restore_labs=False,
        skip_lab_restore=False,
        overwrite_labs=False,
    )


def _authority_session() -> AuthoritySession:
    return AuthoritySession(
        requirement=AuthorityRequirement("primary_ipam", "inventory_ipam"),
        declaration=AuthorityDeclaration(
            "primary_ipam",
            "inventory_ipam",
            "fixture",
        ),
        context=AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
        admission=AuthorityReceipt(
            logical_ref="primary_ipam",
            capability="inventory_ipam",
            provider="fixture",
            provider_identity=_PROVIDER_IDENTITY,
            state="ready",
            result="admitted",
        ),
    )


def _interval_receipt(*, decision: str) -> AuthorityIntervalReceipt:
    return AuthorityIntervalReceipt(
        logical_ref="primary_ipam",
        capability="inventory_ipam",
        provider="fixture",
        provider_identity=_PROVIDER_IDENTITY,
        expected_change="none",
        on_unverifiable="fail",
        interval_status="stable" if decision == "allow" else "drifted",
        completion_status="fresh",
        decision=decision,
        result="authority remained stable"
        if decision == "allow"
        else "authority drifted",
        detection_strength="revision-and-audit",
        freshness_basis="resource revision",
    )


class BlueprintPreflightBypassTest(TestCase):
    def test_successful_deploy_actions_include_access_credentials_and_support(
        self,
    ) -> None:
        payload = _payload()
        payload["access"] = {"type": "gcp-iap-ssh-forward"}
        payload["metadata"] = {"credential_secret": "EVENG_ADMIN_PASSWORD"}
        ns = _namespace(Path("/tmp/runtime"), reason="test")
        ns.root = None
        ns.env = "demo-lab"

        actions = _successful_deploy_actions(ns, payload)

        self.assertEqual(
            actions["access"],
            "hyops blueprint access --env demo-lab --ref test/lab@v1",
        )
        self.assertEqual(
            actions["credentials"],
            "hyops secrets show --env demo-lab --raw EVENG_ADMIN_PASSWORD",
        )
        self.assertEqual(
            actions["support"],
            "https://github.com/sponsors/hybridops-tech",
        )

    def test_mutating_blueprint_bypass_requires_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=_payload(),
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command.run_step_module_command"
                ) as step_command,
            ):
                rc = run_deploy(_namespace(root, reason=None))

        self.assertEqual(rc, OPERATOR_ERROR)
        step_command.assert_not_called()

    def test_bypass_decision_is_propagated_to_executed_steps(self) -> None:
        captured: dict = {}

        def run_step(_step, _payload, ns, _paths):
            captured.update(ns.preflight_context)
            return 0

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=_payload(),
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=AuthoritySession(
                        requirement=AuthorityRequirement(
                            "primary_ipam", "inventory_ipam"
                        ),
                        declaration=AuthorityDeclaration(
                            "primary_ipam", "inventory_ipam", "nautobot"
                        ),
                        context=AuthorityContext(root, root / "state", {}),
                        admission=AuthorityReceipt(
                            logical_ref="primary_ipam",
                            capability="inventory_ipam",
                            provider="nautobot",
                            provider_identity=_PROVIDER_IDENTITY,
                            state="ready",
                            result="admitted",
                            endpoint="https://nautobot.example",
                            revision="2.4",
                        ),
                    ),
                ),
                patch(
                    "hyops.blueprint.command.run_step_module_command",
                    side_effect=run_step,
                ),
            ):
                rc = run_deploy(_namespace(root, reason="controlled provider recovery"))

        self.assertEqual(rc, 0)
        self.assertEqual(captured["scope"], "blueprint")
        self.assertEqual(captured["decision"], "bypass")
        self.assertEqual(captured["status"], "bypassed")
        self.assertEqual(captured["reason"], "controlled provider recovery")
        self.assertEqual(captured["authority"]["logical_authority"], "primary_ipam")
        self.assertEqual(captured["authority"]["provider"], "nautobot")

    def test_checked_decision_is_propagated_to_executed_steps(self) -> None:
        captured: dict = {}

        def run_step(_step, _payload, ns, _paths):
            captured.update(ns.preflight_context)
            return 0

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            preflight_steps = [{"id": "host", "status": "ready"}]
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=_payload(),
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command.compute_preflight",
                    return_value=(preflight_steps, [], []),
                ),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch("hyops.blueprint.command.begin_step_contracts"),
                patch(
                    "hyops.blueprint.command.run_step_module_command",
                    side_effect=run_step,
                ),
            ):
                rc = run_deploy(
                    _namespace(
                        root,
                        skip_preflight=False,
                        reason=None,
                    )
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["scope"], "blueprint")
        self.assertEqual(captured["decision"], "enforce")
        self.assertEqual(captured["status"], "passed")
        self.assertEqual(captured["guarantee"], "established")

    def test_failed_deploy_offers_cleanup(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=_payload(),
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch("hyops.blueprint.command.begin_step_contracts"),
                patch(
                    "hyops.blueprint.command.run_step_module_command", return_value=2
                ),
                patch(
                    "hyops.blueprint.command._failed_deploy_has_resources",
                    return_value=True,
                ),
                patch(
                    "hyops.blueprint.command._offer_failed_deploy_destroy"
                ) as cleanup,
            ):
                rc = run_deploy(_namespace(root, reason="controlled provider recovery"))

        self.assertEqual(rc, OPERATOR_ERROR)
        cleanup.assert_called_once()

    def test_authority_interval_receipt_is_recorded_after_dispatch(self) -> None:
        payload = _payload()
        payload["steps"][0]["contracts"] = {
            "authority_observation": {
                "expected_change": "none",
                "on_unverifiable": "fail",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            ns.json = True
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=_authority_session(),
                ),
                patch(
                    "hyops.blueprint.command.run_step_module_command", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.complete_step_authority",
                    return_value=_interval_receipt(decision="allow"),
                ) as complete,
                patch("builtins.print") as output,
            ):
                rc = run_deploy(ns)

            rendered = json.loads(output.call_args_list[-1].args[0])
            persisted = json.loads(
                Path(rendered["run_record"]).read_text(encoding="utf-8")
            )

        self.assertEqual(rc, 0)
        self.assertEqual(
            rendered["steps"][0]["authority_interval"]["decision"],
            "allow",
        )
        self.assertEqual(
            persisted["steps"][0]["authority_interval"]["decision"],
            "allow",
        )
        complete.assert_called_once()

    def test_authority_interval_denial_fails_the_step(self) -> None:
        payload = _payload()
        payload["steps"][0]["contracts"] = {
            "authority_observation": {
                "expected_change": "none",
                "on_unverifiable": "fail",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            ns.json = True
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=_authority_session(),
                ),
                patch(
                    "hyops.blueprint.command.run_step_module_command", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.complete_step_authority",
                    return_value=_interval_receipt(decision="deny"),
                ),
                patch(
                    "hyops.blueprint.command._failed_deploy_has_resources",
                    return_value=False,
                ),
                patch("builtins.print") as output,
            ):
                rc = run_deploy(ns)

        rendered = json.loads(output.call_args_list[-1].args[0])
        self.assertEqual(rc, OPERATOR_ERROR)
        self.assertEqual(
            rendered["steps"][0]["authority_interval"]["decision"],
            "deny",
        )
        self.assertEqual(rendered["steps"][0]["module_rc"], 0)

    def test_failed_dispatch_still_records_closing_authority_observation(self) -> None:
        payload = _payload()
        payload["steps"][0]["contracts"] = {
            "authority_observation": {
                "expected_change": "none",
                "on_unverifiable": "fail",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            ns.json = True
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=_authority_session(),
                ),
                patch(
                    "hyops.blueprint.command.run_step_module_command", return_value=2
                ),
                patch(
                    "hyops.blueprint.command.complete_step_authority",
                    return_value=_interval_receipt(decision="allow"),
                ) as complete,
                patch(
                    "hyops.blueprint.command._failed_deploy_has_resources",
                    return_value=False,
                ),
                patch("builtins.print") as output,
            ):
                rc = run_deploy(ns)

        rendered = json.loads(output.call_args_list[-1].args[0])
        self.assertEqual(rc, OPERATOR_ERROR)
        self.assertEqual(
            rendered["steps"][0]["authority_interval"]["decision"],
            "allow",
        )
        self.assertEqual(rendered["steps"][0]["module_rc"], OPERATOR_ERROR)
        complete.assert_called_once()

    def test_cancelled_dispatch_records_closing_authority_observation(self) -> None:
        payload = _payload()
        payload["steps"][0]["contracts"] = {
            "authority_observation": {
                "expected_change": "none",
                "on_unverifiable": "fail",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            ns.json = True
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=_authority_session(),
                ),
                patch(
                    "hyops.blueprint.command.run_step_module_command",
                    return_value=CANCELLED,
                ),
                patch(
                    "hyops.blueprint.command.complete_step_authority",
                    return_value=_interval_receipt(decision="allow"),
                ) as complete,
                patch("builtins.print") as output,
            ):
                rc = run_deploy(ns)

        rendered = json.loads(output.call_args_list[-1].args[0])
        self.assertEqual(rc, CANCELLED)
        self.assertEqual(
            rendered["steps"][0]["authority_interval"]["decision"],
            "allow",
        )
        complete.assert_called_once()

    def test_unserializable_authority_evidence_fails_cleanly(self) -> None:
        payload = _payload()
        payload["steps"][0]["contracts"] = {
            "authority_observation": {
                "expected_change": "none",
                "on_unverifiable": "fail",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            ns.json = True
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=_authority_session(),
                ),
                patch(
                    "hyops.blueprint.command.run_step_module_command", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.complete_step_authority",
                    return_value=_interval_receipt(decision="allow"),
                ),
                patch(
                    "hyops.blueprint.command.EvidenceWriter.write_json",
                    side_effect=TypeError("unsupported evidence value"),
                ),
                patch("builtins.print") as output,
            ):
                rc = run_deploy(ns)

        rendered = json.loads(output.call_args_list[-1].args[0])
        self.assertEqual(rc, OPERATOR_ERROR)
        self.assertEqual(rendered["status"], "failed")
        self.assertIn("authority_evidence", rendered["required_failures"])

    def test_state_skip_cannot_bypass_authority_interval_denial(self) -> None:
        payload = _payload()
        payload["steps"][0]["skip_if_state_ok"] = True
        payload["steps"][0]["contracts"] = {
            "authority_observation": {
                "expected_change": "none",
                "on_unverifiable": "fail",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=True),
                patch(
                    "hyops.blueprint.command.explicit_step_inputs_changed",
                    return_value=(False, ""),
                ),
                patch(
                    "hyops.blueprint.command.begin_step_contracts",
                    return_value=_authority_session(),
                ),
                patch(
                    "hyops.blueprint.command.complete_step_authority",
                    return_value=_interval_receipt(decision="deny"),
                ),
                patch("hyops.blueprint.command.run_step_module_command") as command,
                patch(
                    "hyops.blueprint.command._failed_deploy_has_resources",
                    return_value=False,
                ),
            ):
                rc = run_deploy(ns)

        self.assertEqual(rc, OPERATOR_ERROR)
        command.assert_not_called()

    def test_existing_state_skip_without_interval_keeps_legacy_path(self) -> None:
        payload = _payload()
        payload["steps"][0]["skip_if_state_ok"] = True
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            ns = _namespace(root, reason="controlled provider recovery")
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value=payload,
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths", return_value=paths
                ),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command._confirm_deploy_if_needed", return_value=0
                ),
                patch(
                    "hyops.blueprint.command.resolved_step_inputs_file",
                    return_value=None,
                ),
                patch("hyops.blueprint.command.module_state_ok", return_value=True),
                patch(
                    "hyops.blueprint.command.explicit_step_inputs_changed",
                    return_value=(False, ""),
                ),
                patch("hyops.blueprint.command.begin_step_contracts") as admission,
                patch("hyops.blueprint.command.run_step_module_command") as command,
            ):
                rc = run_deploy(ns)

        self.assertEqual(rc, 0)
        admission.assert_not_called()
        command.assert_not_called()

    def test_runner_forwards_bypass_reason_to_remote_command(self) -> None:
        ns = SimpleNamespace(
            runner_blueprint_cmd="deploy",
            execute=True,
            skip_preflight=True,
            preflight_bypass_reason="controlled provider recovery",
            yes=True,
        )
        ctx = SimpleNamespace(remote_hyops="/opt/hybridops/bin/hyops")

        command = _remote_blueprint_command(
            ns,
            runtime_root="/tmp/runtime",
            remote_blueprint_path="/tmp/runtime/config/blueprints/lab.yml",
            ctx=ctx,
        )

        self.assertIn("--skip-preflight", command)
        reason_index = command.index("--preflight-bypass-reason")
        self.assertEqual(command[reason_index + 1], "controlled provider recovery")


if __name__ == "__main__":
    import unittest

    unittest.main()
