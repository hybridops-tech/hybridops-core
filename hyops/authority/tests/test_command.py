from __future__ import annotations

import argparse
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from hyops.authority import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityObservation,
    AuthorityObservationPolicy,
    AuthorityRequirement,
    AuthorityResolver,
    command,
)
from hyops.authority.models import AuthorityProviderIdentity
from hyops.authority.registry import AuthorityProviderRegistry
from hyops.runtime.exitcodes import OPERATOR_ERROR

_IDENTITY = {
    "source": "builtin",
    "distribution": "hybridops-core",
    "version": "0.1.6",
    "entry_point": "hyops.authority.providers.kubernetes:KubernetesAuthorityProvider",
    "contract_version": "1",
}


def _observation(
    token: str,
    scope: str = "kubernetes:configmap/change-authority",
    observed_at: str = "2026-11-21T12:00:00Z",
) -> dict[str, str]:
    return {
        "token": token,
        "observed_at": observed_at,
        "scope": scope,
        "strength": "kubernetes-resource-version",
    }


class _Provider:
    name = "fixture"
    capabilities = frozenset({"change_control", "resource_authority"})

    def validate_configuration(self, declaration, context) -> None:
        del declaration, context

    def evaluate(self, declaration, context):
        del declaration, context
        raise AssertionError("provider evaluation is not used by inventory")


class AuthorityCommandTests(unittest.TestCase):
    def test_run_record_read_remains_bounded_after_size_check(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps({"padding": "x" * 128}), encoding="utf-8")
            with (
                patch.object(command, "_MAX_RECORD_BYTES", 64),
                patch.object(Path, "is_file", return_value=True),
                patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1)),
                self.assertRaisesRegex(ValueError, "exceeds the 16 MiB"),
            ):
                command._load_run_record(str(path))

    def test_providers_lists_registered_capabilities(self) -> None:
        registry = AuthorityProviderRegistry()
        registry.register(
            _Provider(),
            identity=AuthorityProviderIdentity(
                source="direct",
                distribution="hybridops-core",
                version="0.1.6",
                entry_point="hyops.authority.tests.test_command:_Provider",
            ),
        )
        output = io.StringIO()

        with (
            patch.object(command, "default_authority_registry", return_value=registry),
            redirect_stdout(output),
        ):
            result = command.run_providers(argparse.Namespace(json=True))

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(
            payload,
            {
                "providers": [
                    {
                        "name": "fixture",
                        "capabilities": ["change_control", "resource_authority"],
                        "identity": {
                            "source": "direct",
                            "distribution": "hybridops-core",
                            "version": "0.1.6",
                            "entry_point": (
                                "hyops.authority.tests.test_command:_Provider"
                            ),
                            "contract_version": "1",
                        },
                    }
                ]
            },
        )

    def test_inspect_emits_only_safe_authority_outcomes(self) -> None:
        before_token = "SECRET-BEFORE" * 50
        after_token = "SECRET-AFTER" * 50
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "failed",
            "steps": [
                {
                    "id": "network",
                    "status": "failed",
                    "authority": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "verified_state": "ready",
                        "result": "admitted",
                        "provider_identity": _IDENTITY,
                        "endpoint": "https://private.example.invalid",
                        "observation": _observation(before_token),
                    },
                    "authority_interval": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "interval_status": "drifted",
                        "completion_status": "fresh",
                        "decision": "deny",
                        "expected_change": "none",
                        "on_unverifiable": "fail",
                        "detection_strength": "kubernetes-resource-version",
                        "freshness_basis": "fresh Kubernetes API GET",
                        "result": "authority changed during the operation",
                        "provider_identity": _IDENTITY,
                        "before": _observation(before_token),
                        "after": _observation(after_token),
                    },
                }
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=True)
                )

        rendered = output.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(result, 0)
        self.assertEqual(payload["authority_outcomes"][0]["decision"], "deny")
        self.assertEqual(payload["authority_outcomes"][0]["step"], "network")
        self.assertEqual(len(payload["record_sha256"]), 64)
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("private.example.invalid", rendered)

    def test_inspect_rejects_malformed_step_collection(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(
                json.dumps(
                    {
                        "blueprint_ref": "platform/production@v1",
                        "run_id": "deploy-42",
                        "status": "failed",
                        "steps": {},
                    }
                ),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=False)
                )

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertIn("run record steps must be a list", stderr.getvalue())

    def test_inspect_validates_steps_without_authority_evidence(self) -> None:
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "failed",
            "steps": [{"id": "network", "status": "invalid"}],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=False)
                )

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertIn("step 'network' status is invalid", stderr.getvalue())

    def test_inspect_rejects_inconsistent_interval_outcomes(self) -> None:
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "ok",
            "steps": [
                {
                    "id": "network",
                    "status": "failed",
                    "authority": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "verified_state": "ready",
                        "result": "admitted",
                        "provider_identity": _IDENTITY,
                        "observation": _observation("before"),
                    },
                    "authority_interval": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "provider_identity": _IDENTITY,
                        "interval_status": "drifted",
                        "completion_status": "fresh",
                        "decision": "allow",
                        "expected_change": "none",
                        "on_unverifiable": "fail",
                        "result": "changed",
                        "detection_strength": "revision",
                        "freshness_basis": "live read",
                        "before": _observation("before"),
                        "after": _observation("after"),
                    },
                }
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            cases = (
                ("failed", "allow", "decision contradicts"),
                ("ok", "deny", "is ok but its authority decision is deny"),
            )
            for step_status, decision, message in cases:
                with self.subTest(step_status=step_status, decision=decision):
                    record["steps"][0]["status"] = step_status
                    record["steps"][0]["authority_interval"]["decision"] = decision
                    path.write_text(json.dumps(record), encoding="utf-8")
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        result = command.run_inspect(
                            argparse.Namespace(record=str(path), json=False)
                        )

                    self.assertEqual(result, OPERATOR_ERROR)
                    self.assertIn(message, stderr.getvalue())

    def test_inspect_rejects_interval_not_bound_to_admission_observation(self) -> None:
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "ok",
            "steps": [
                {
                    "id": "network",
                    "status": "ok",
                    "authority": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "verified_state": "ready",
                        "result": "admitted",
                        "provider_identity": _IDENTITY,
                        "observation": _observation("admission"),
                    },
                    "authority_interval": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "provider_identity": _IDENTITY,
                        "interval_status": "stable",
                        "completion_status": "fresh",
                        "decision": "allow",
                        "expected_change": "none",
                        "on_unverifiable": "fail",
                        "result": "stable",
                        "detection_strength": "revision",
                        "freshness_basis": "live read",
                        "before": _observation("different"),
                        "after": _observation("different"),
                    },
                }
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=False)
                )

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertIn("does not match admission evidence", stderr.getvalue())

    def test_inspect_accepts_unverifiable_scope_change(self) -> None:
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "failed",
            "steps": [
                {
                    "id": "network",
                    "status": "failed",
                    "authority": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "verified_state": "ready",
                        "result": "admitted",
                        "provider_identity": _IDENTITY,
                        "observation": _observation("before"),
                    },
                    "authority_interval": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "provider_identity": _IDENTITY,
                        "interval_status": "unverifiable",
                        "completion_status": "unverifiable",
                        "decision": "deny",
                        "expected_change": "none",
                        "on_unverifiable": "fail",
                        "result": "authority scope changed",
                        "detection_strength": "none",
                        "freshness_basis": "none",
                        "before": _observation("before"),
                        "after": _observation(
                            "after",
                            "kubernetes:configmap/replacement-authority",
                        ),
                    },
                }
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=True)
                )

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output.getvalue())["authority_outcomes"][0]["decision"],
            "deny",
        )

    def test_inspect_accepts_stale_completion_observation(self) -> None:
        before = _observation("before")
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "failed",
            "steps": [
                {
                    "id": "network",
                    "status": "failed",
                    "authority": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "verified_state": "ready",
                        "result": "admitted",
                        "provider_identity": _IDENTITY,
                        "observation": before,
                    },
                    "authority_interval": {
                        "logical_authority": "change_control",
                        "provider": "kubernetes",
                        "capability": "resource_authority",
                        "provider_identity": _IDENTITY,
                        "interval_status": "unverifiable",
                        "completion_status": "stale",
                        "decision": "deny",
                        "expected_change": "none",
                        "on_unverifiable": "fail",
                        "result": "completion observation is stale",
                        "detection_strength": "revision",
                        "freshness_basis": "observation time",
                        "before": before,
                        "after": _observation(
                            "after",
                            observed_at="2026-11-21T11:59:00Z",
                        ),
                    },
                }
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=True)
                )

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output.getvalue())["authority_outcomes"][0]["decision"],
            "deny",
        )

    def test_inspect_accepts_fail_closed_receipt_under_record_policy(self) -> None:
        class FailingCompletionProvider:
            name = "fixture"
            capabilities = frozenset({"change_control"})

            def __init__(self) -> None:
                self.calls = 0

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                self.calls += 1
                if self.calls > 1:
                    raise ValueError("completion unavailable")
                return AuthorityEvaluation(
                    healthy=True,
                    state="ready",
                    result="admitted",
                    observation=AuthorityObservation(
                        token="revision:1",
                        observed_at="2026-11-21T12:00:00Z",
                        scope="fixture:change",
                        strength="revision",
                    ),
                )

        registry = AuthorityProviderRegistry()
        registry.register(FailingCompletionProvider())
        resolver = AuthorityResolver(registry)
        requirement = AuthorityRequirement("change", "change_control")
        declaration = AuthorityDeclaration("change", "change_control", "fixture")
        policy = AuthorityObservationPolicy("none", "record")
        session = resolver.begin(
            requirement,
            {"change": declaration},
            AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
            policy=policy,
        )
        interval = resolver.complete(
            session,
            policy,
            completion_floor="2026-11-21T12:00:01Z",
        )
        record = {
            "blueprint_ref": "platform/production@v1",
            "run_id": "deploy-42",
            "status": "failed",
            "steps": [
                {
                    "id": "network",
                    "status": "failed",
                    "authority": session.admission.to_evidence(),
                    "authority_interval": interval.to_evidence(),
                }
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "deploy.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = command.run_inspect(
                    argparse.Namespace(record=str(path), json=True)
                )

        self.assertEqual(interval.decision, "deny")
        self.assertEqual(result, 0)

    def test_provider_inventory_fails_when_discovery_is_incomplete(self) -> None:
        registry = AuthorityProviderRegistry()
        registry.record_discovery_error("broken plugin")
        stderr = io.StringIO()

        with (
            patch.object(command, "default_authority_registry", return_value=registry),
            redirect_stderr(stderr),
        ):
            result = command.run_providers(argparse.Namespace(json=True))

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertIn("discovery is incomplete", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
