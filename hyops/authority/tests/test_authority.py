from __future__ import annotations

import json
import os
import re
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from hyops.authority import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityIntervalEvaluation,
    AuthorityObservation,
    AuthorityObservationPolicy,
    AuthorityRequirement,
    AuthorityResolver,
    default_authority_registry,
)
from hyops.authority.registry import AuthorityProviderRegistry
from hyops.blueprint.contracts import (
    begin_step_contracts,
    complete_step_authority,
    enforce_step_contracts,
)
from hyops.blueprint.schema import validate_blueprint
from hyops.runtime.module_state import write_module_state


class _Response:
    def __init__(
        self,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    def read(self, size: int = -1) -> bytes:
        return self.body[:size] if size >= 0 else self.body


def _paths(root: Path):
    return SimpleNamespace(root=root, state_dir=root / "state")


def _write_netbox_state(root: Path, *, updated_at: str | None = None) -> None:
    payload = {
        "module_ref": "platform/onprem/netbox",
        "status": "ok",
        "run_id": "apply-test",
    }
    if updated_at:
        payload["updated_at"] = updated_at
    write_module_state(root / "state", "platform/onprem/netbox", payload)


def _canonical_payload(provider: str, config: dict | None = None) -> dict:
    return {
        "policy": {},
        "authorities": {
            "primary_ipam": {
                "capability": "inventory_ipam",
                "provider": provider,
                "config": config or {},
            }
        },
    }


def _canonical_step() -> dict:
    return {
        "contracts": {
            "addressing_mode": "ipam",
            "requires_module_state_ok": [],
            "requires_authority": {
                "ref": "primary_ipam",
                "capability": "inventory_ipam",
            },
        }
    }


def _kubernetes_payload() -> dict:
    return {
        "policy": {},
        "authorities": {
            "change_control": {
                "capability": "resource_authority",
                "provider": "kubernetes",
                "config": {
                    "resource_path": (
                        "/api/v1/namespaces/platform/configmaps/change-authority"
                    ),
                },
            }
        },
    }


def _kubernetes_step(*, expected_change: str = "none") -> dict:
    return {
        "contracts": {
            "addressing_mode": "static",
            "requires_module_state_ok": [],
            "requires_authority": {
                "ref": "change_control",
                "capability": "resource_authority",
            },
            "authority_observation": {
                "expected_change": expected_change,
                "on_unverifiable": "fail",
            },
        }
    }


def _kubernetes_resource(
    resource_version: str,
    *,
    uid: str = "4ea4ee4d-98e5-4121-b7e8-f9e9fbcd78aa",
) -> bytes:
    return json.dumps(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "change-authority",
                "namespace": "platform",
                "resourceVersion": resource_version,
                "uid": uid,
            },
            "data": {"approved_revision": "release-42"},
        }
    ).encode("utf-8")


class AuthorityContractTests(unittest.TestCase):
    @staticmethod
    def _interval_resolver(
        interval: AuthorityIntervalEvaluation,
        *,
        after_observed_at: str = "2026-09-28T12:00:02Z",
        after_token: str = "revision-11",
    ) -> tuple[AuthorityResolver, AuthorityRequirement, dict, AuthorityContext, object]:
        class FixtureProvider:
            name = "fixture"
            capabilities = frozenset({"inventory_ipam"})

            def __init__(self) -> None:
                self.evaluations = [
                    AuthorityEvaluation(
                        healthy=True,
                        state="ready",
                        result="admitted",
                        observation=AuthorityObservation(
                            token="revision-10",
                            observed_at="2026-09-28T12:00:00Z",
                            scope="site:42",
                            strength="revision-and-audit",
                        ),
                    ),
                    AuthorityEvaluation(
                        healthy=True,
                        state="ready",
                        result="completion observed",
                        observation=AuthorityObservation(
                            token=after_token,
                            observed_at=after_observed_at,
                            scope="site:42",
                            strength="revision-and-audit",
                        ),
                    ),
                ]
                self.received_policy = None

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return self.evaluations.pop(0)

            def interval_verifiable(
                self,
                declaration,
                context,
                before,
                policy,
            ) -> bool:
                del declaration, context, before, policy
                return True

            def evaluate_interval(
                self,
                declaration,
                context,
                before,
                after,
                policy,
                completion_floor,
            ) -> AuthorityIntervalEvaluation:
                del declaration, context, before, after, completion_floor
                self.received_policy = policy
                return interval

        provider = FixtureProvider()
        registry = AuthorityProviderRegistry()
        registry.register(provider)
        requirement = AuthorityRequirement("primary_ipam", "inventory_ipam")
        declarations = {
            "primary_ipam": AuthorityDeclaration(
                "primary_ipam",
                "inventory_ipam",
                "fixture",
            )
        }
        context = AuthorityContext(Path("/tmp"), Path("/tmp/state"), {})
        return AuthorityResolver(registry), requirement, declarations, context, provider

    def test_resolver_uses_registered_provider_without_product_branching(self) -> None:
        class FixtureProvider:
            name = "fixture"
            capabilities = frozenset({"inventory_ipam"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return AuthorityEvaluation(
                    healthy=True,
                    state="ready",
                    result="admitted",
                    instance="fixture-one",
                )

        registry = AuthorityProviderRegistry()
        registry.register(FixtureProvider())
        receipt = AuthorityResolver(registry).enforce(
            AuthorityRequirement("primary_ipam", "inventory_ipam"),
            {
                "primary_ipam": AuthorityDeclaration(
                    "primary_ipam",
                    "inventory_ipam",
                    "fixture",
                )
            },
            AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
        )

        self.assertEqual(receipt.provider, "fixture")
        self.assertEqual(receipt.instance, "fixture-one")

    def test_interval_observation_allows_stable_fresh_completion(self) -> None:
        resolver, requirement, declarations, context, provider = self._interval_resolver(
            AuthorityIntervalEvaluation(
                interval_status="stable",
                completion_status="fresh",
                result="authority remained stable",
                detection_strength="revision-and-audit",
                freshness_basis="resource revision",
            )
        )
        session = resolver.begin(requirement, declarations, context)
        policy = AuthorityObservationPolicy("operation", "fail")

        receipt = resolver.complete(
            session,
            policy,
            completion_floor="2026-09-28T12:00:01Z",
        )

        self.assertEqual(receipt.decision, "allow")
        self.assertEqual(receipt.interval_status, "stable")
        self.assertEqual(receipt.completion_status, "fresh")
        self.assertEqual(receipt.before.token, "revision-10")
        self.assertEqual(receipt.after.token, "revision-11")
        self.assertEqual(provider.received_policy, policy)

    def test_non_boolean_health_cannot_admit_or_complete(self) -> None:
        stable = AuthorityIntervalEvaluation(
            interval_status="stable",
            completion_status="fresh",
            result="stable",
            detection_strength="revision",
            freshness_basis="resource revision",
        )
        policy = AuthorityObservationPolicy("none", "record")
        for healthy in ("false", "true", 1, 0, None):
            with self.subTest(healthy=healthy):
                resolver, requirement, declarations, context, provider = self._interval_resolver(
                    stable
                )
                session = resolver.begin(requirement, declarations, context, policy=policy)
                malformed = replace(provider.evaluations[0], healthy=healthy)
                with patch.object(provider, "evaluate", return_value=malformed):
                    with self.assertRaisesRegex(ValueError, "returned an invalid evaluation"):
                        resolver.enforce(requirement, declarations, context)
                    receipt = resolver.complete(
                        session,
                        policy,
                        completion_floor="2026-09-28T12:00:01Z",
                    )

                self.assertEqual(receipt.decision, "deny")
                self.assertEqual(receipt.completion_status, "unverifiable")
                self.assertIn("invalid completion authority evaluation", receipt.result)
                self.assertIsNone(provider.received_policy)

    def test_strict_interval_policy_is_rejected_before_dispatch_when_unavailable(self) -> None:
        class SnapshotProvider:
            name = "snapshot"
            capabilities = frozenset({"inventory_ipam"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return AuthorityEvaluation(
                    healthy=True,
                    state="ready",
                    result="admitted",
                    observation=AuthorityObservation(
                        token="snapshot-1",
                        observed_at="2026-09-28T12:00:00Z",
                        scope="site:42",
                        strength="snapshot",
                    ),
                )

        registry = AuthorityProviderRegistry()
        registry.register(SnapshotProvider())
        resolver = AuthorityResolver(registry)

        with self.assertRaisesRegex(
            ValueError,
            "interval evidence required by policy is unavailable before dispatch",
        ):
            resolver.begin(
                AuthorityRequirement("primary_ipam", "inventory_ipam"),
                {
                    "primary_ipam": AuthorityDeclaration(
                        "primary_ipam",
                        "inventory_ipam",
                        "snapshot",
                    )
                },
                AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
                policy=AuthorityObservationPolicy("none", "fail"),
            )

    def test_observation_metadata_must_be_json_serializable(self) -> None:
        class InvalidProvider:
            name = "invalid"
            capabilities = frozenset({"inventory_ipam"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return AuthorityEvaluation(
                    healthy=True,
                    state="ready",
                    result="admitted",
                    observation=AuthorityObservation(
                        token="snapshot-1",
                        observed_at="2026-09-28T12:00:00Z",
                        scope="site:42",
                        strength="snapshot",
                        metadata={"invalid": object()},
                    ),
                )

        registry = AuthorityProviderRegistry()
        registry.register(InvalidProvider())

        with self.assertRaisesRegex(ValueError, "must be JSON serializable"):
            AuthorityResolver(registry).begin(
                AuthorityRequirement("primary_ipam", "inventory_ipam"),
                {
                    "primary_ipam": AuthorityDeclaration(
                        "primary_ipam",
                        "inventory_ipam",
                        "invalid",
                    )
                },
                AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
            )

    def test_admission_evidence_must_be_json_serializable(self) -> None:
        class InvalidProvider:
            name = "invalid"
            capabilities = frozenset({"inventory_ipam"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return AuthorityEvaluation(
                    healthy=True,
                    state="ready",
                    result="admitted",
                    freshness={"invalid": object()},
                )

        registry = AuthorityProviderRegistry()
        registry.register(InvalidProvider())

        with self.assertRaisesRegex(ValueError, "admission evidence must be JSON serializable"):
            AuthorityResolver(registry).begin(
                AuthorityRequirement("primary_ipam", "inventory_ipam"),
                {
                    "primary_ipam": AuthorityDeclaration(
                        "primary_ipam",
                        "inventory_ipam",
                        "invalid",
                    )
                },
                AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
            )

    def test_interval_drift_always_denies_completion(self) -> None:
        resolver, requirement, declarations, context, _ = self._interval_resolver(
            AuthorityIntervalEvaluation(
                interval_status="drifted",
                completion_status="fresh",
                result="out-of-band mutation observed",
                detection_strength="audit-history",
                freshness_basis="resource revision",
            ),
            after_token="revision-10",
        )
        session = resolver.begin(requirement, declarations, context)

        receipt = resolver.complete(
            session,
            AuthorityObservationPolicy("none", "record"),
            completion_floor="2026-09-28T12:00:01Z",
        )

        self.assertEqual(receipt.decision, "deny")
        self.assertEqual(receipt.interval_status, "drifted")
        self.assertEqual(receipt.before.token, receipt.after.token)

    def test_unverifiable_interval_obeys_policy(self) -> None:
        evaluation = AuthorityIntervalEvaluation(
            interval_status="unverifiable",
            completion_status="fresh",
            result="only point-in-time state is available",
            detection_strength="snapshot",
            freshness_basis="live read",
        )
        for action, expected in (("fail", "deny"), ("record", "record")):
            with self.subTest(action=action):
                resolver, requirement, declarations, context, _ = self._interval_resolver(
                    evaluation
                )
                session = resolver.begin(requirement, declarations, context)
                receipt = resolver.complete(
                    session,
                    AuthorityObservationPolicy("none", action),
                    completion_floor="2026-09-28T12:00:01Z",
                )
                self.assertEqual(receipt.decision, expected)

    def test_invalid_provider_interval_cannot_be_permitted_by_record_policy(self) -> None:
        resolver, requirement, declarations, context, _ = self._interval_resolver(
            AuthorityIntervalEvaluation(
                interval_status="unknown",
                completion_status="fresh",
                result="invalid",
                detection_strength="revision",
                freshness_basis="resource revision",
            )
        )
        session = resolver.begin(requirement, declarations, context)

        receipt = resolver.complete(
            session,
            AuthorityObservationPolicy("none", "record"),
            completion_floor="2026-09-28T12:00:01Z",
        )

        self.assertEqual(receipt.decision, "deny")
        self.assertIn("invalid authority interval status", receipt.result)
        self.assertEqual(receipt.after.token, "revision-11")

    def test_completion_observation_must_follow_completion_floor(self) -> None:
        resolver, requirement, declarations, context, _ = self._interval_resolver(
            AuthorityIntervalEvaluation(
                interval_status="stable",
                completion_status="fresh",
                result="stable",
                detection_strength="revision",
                freshness_basis="resource revision",
            ),
            after_observed_at="2026-09-28T12:00:00Z",
        )
        session = resolver.begin(requirement, declarations, context)

        receipt = resolver.complete(
            session,
            AuthorityObservationPolicy("none", "record"),
            completion_floor="2026-09-28T12:00:01Z",
        )

        self.assertEqual(receipt.decision, "deny")
        self.assertEqual(receipt.completion_status, "stale")

    def test_provider_without_interval_observations_is_explicitly_unverifiable(self) -> None:
        class SnapshotProvider:
            name = "snapshot"
            capabilities = frozenset({"inventory_ipam"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return AuthorityEvaluation(
                    healthy=True,
                    state="ready",
                    result="admitted",
                )

        registry = AuthorityProviderRegistry()
        registry.register(SnapshotProvider())
        resolver = AuthorityResolver(registry)
        requirement = AuthorityRequirement("primary_ipam", "inventory_ipam")
        declarations = {
            "primary_ipam": AuthorityDeclaration(
                "primary_ipam",
                "inventory_ipam",
                "snapshot",
            )
        }
        session = resolver.begin(
            requirement,
            declarations,
            AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
        )

        receipt = resolver.complete(
            session,
            AuthorityObservationPolicy("none", "record"),
            completion_floor="2026-09-28T12:00:01Z",
        )

        self.assertEqual(receipt.interval_status, "unverifiable")
        self.assertEqual(receipt.decision, "record")
        self.assertNotIn("secret", json.dumps(receipt.to_evidence()))

    def test_legacy_netbox_contract_remains_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_netbox_state(root)
            step = {
                "contracts": {
                    "addressing_mode": "ipam",
                    "requires_authority": "netbox",
                }
            }
            payload = {
                "policy": {
                    "ipam_authority": "netbox",
                    "netbox_live_api_check": False,
                }
            }
            with patch.dict(
                os.environ,
                {"HYOPS_NETBOX_AUTHORITY_ROOT": str(root)},
                clear=True,
            ):
                receipt = enforce_step_contracts(step, payload, _paths(root))

        self.assertEqual(receipt.provider, "netbox")
        self.assertEqual(receipt.logical_ref, "legacy_netbox")
        self.assertEqual(receipt.state, "ok")

    def test_logical_contract_resolves_netbox(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_netbox_state(root, updated_at="2026-09-14T10:00:00Z")
            with patch.dict(
                os.environ,
                {"HYOPS_NETBOX_AUTHORITY_ROOT": str(root)},
                clear=True,
            ):
                receipt = enforce_step_contracts(
                    _canonical_step(),
                    _canonical_payload("netbox"),
                    _paths(root),
                )

        self.assertEqual(receipt.logical_ref, "primary_ipam")
        self.assertEqual(receipt.capability, "inventory_ipam")
        self.assertEqual(receipt.provider, "netbox")
        self.assertEqual(receipt.result, "admitted")

    def test_legacy_netbox_live_check_remains_functional(self) -> None:
        requests = []

        def respond(request, **kwargs):
            del kwargs
            requests.append(request)
            return _Response()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_netbox_state(root)
            step = {
                "contracts": {
                    "addressing_mode": "ipam",
                    "requires_authority": "netbox",
                }
            }
            payload = {
                "policy": {
                    "ipam_authority": "netbox",
                    "netbox_live_api_check": True,
                }
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "HYOPS_NETBOX_AUTHORITY_ROOT": str(root),
                        "NETBOX_API_URL": "https://netbox.example/api/",
                        "NETBOX_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.netbox.open_no_redirect",
                    side_effect=respond,
                ),
            ):
                receipt = enforce_step_contracts(step, payload, _paths(root))

        self.assertEqual(receipt.provider, "netbox")
        self.assertEqual(receipt.endpoint, "https://netbox.example")
        self.assertTrue(requests[0].full_url.endswith("/api/dcim/sites/?limit=1"))
        self.assertNotIn("secret-token", json.dumps(receipt.to_evidence()))

    def test_unhealthy_netbox_state_blocks_operation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_module_state(
                root / "state",
                "platform/onprem/netbox",
                {"status": "error"},
            )
            with patch.dict(
                os.environ,
                {"HYOPS_NETBOX_AUTHORITY_ROOT": str(root)},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "not ready.*status=error"):
                    enforce_step_contracts(
                        _canonical_step(),
                        _canonical_payload("netbox"),
                        _paths(root),
                    )

    def test_same_logical_contract_resolves_nautobot(self) -> None:
        requests = []

        def respond(request, **kwargs):
            del kwargs
            requests.append(request)
            if request.full_url.endswith("/health/"):
                return _Response()
            return _Response(
                headers={"API-Version": "2.4"},
                body=b'{"count": 0, "results": []}',
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "NAUTOBOT_API_URL": "https://nautobot.example/nautobot/api/",
                "NAUTOBOT_API_TOKEN": "secret-token",
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch(
                    "hyops.authority.providers.nautobot.open_no_redirect",
                    side_effect=respond,
                ),
            ):
                receipt = enforce_step_contracts(
                    _canonical_step(),
                    _canonical_payload("nautobot"),
                    _paths(root),
                )

        evidence = receipt.to_evidence()
        self.assertEqual(evidence["logical_authority"], "primary_ipam")
        self.assertEqual(evidence["provider"], "nautobot")
        self.assertEqual(evidence["revision"], "2.4")
        self.assertEqual(len(requests), 2)
        self.assertNotIn("Authorization", requests[0].headers)
        self.assertEqual(
            requests[1].full_url,
            "https://nautobot.example/nautobot/api/ipam/prefixes/?limit=1",
        )
        self.assertNotIn("secret-token", json.dumps(evidence))

    def test_nautobot_records_fresh_snapshot_and_unverifiable_interval(self) -> None:
        def respond(request, **kwargs):
            del kwargs
            if request.full_url.endswith("/health/"):
                return _Response()
            return _Response(
                headers={"API-Version": "2.4"},
                body=b'{"count": 1, "results": [{"id": "prefix-1"}]}',
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "NAUTOBOT_API_URL": "https://nautobot.example/nautobot/api/",
                "NAUTOBOT_API_TOKEN": "secret-token",
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch(
                    "hyops.authority.providers.nautobot.open_no_redirect",
                    side_effect=respond,
                ),
            ):
                session = begin_step_contracts(
                    _canonical_step(),
                    _canonical_payload("nautobot"),
                    _paths(root),
                    observation_policy=AuthorityObservationPolicy("none", "record"),
                )
                floor = datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                ).replace("+00:00", "Z")
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "record"),
                    completion_floor=floor,
                )

        self.assertEqual(receipt.interval_status, "unverifiable")
        self.assertEqual(receipt.completion_status, "fresh")
        self.assertEqual(receipt.decision, "record")
        self.assertEqual(receipt.detection_strength, "snapshot")
        self.assertTrue(receipt.before.token.startswith("sha256:"))
        self.assertTrue(receipt.after.token.startswith("sha256:"))
        self.assertEqual(
            receipt.after.scope,
            "https://nautobot.example/nautobot/api/ipam/prefixes/?limit=1",
        )
        self.assertNotIn("secret-token", json.dumps(receipt.to_evidence()))

    def test_strict_nautobot_interval_policy_fails_before_dispatch(self) -> None:
        def respond(request, **kwargs):
            del kwargs
            if request.full_url.endswith("/health/"):
                return _Response()
            return _Response(body=b'{"count": 0, "results": []}')

        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "NAUTOBOT_API_URL": "https://nautobot.example/nautobot/api/",
                        "NAUTOBOT_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.nautobot.open_no_redirect",
                    side_effect=respond,
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "cannot establish the interval evidence required by policy",
                ):
                    begin_step_contracts(
                        _canonical_step(),
                        _canonical_payload("nautobot"),
                        _paths(Path(tmp)),
                        observation_policy=AuthorityObservationPolicy("none", "fail"),
                    )

    def test_kubernetes_resource_version_establishes_stable_interval(self) -> None:
        responses = [
            _Response(body=_kubernetes_resource("101")),
            _Response(body=_kubernetes_resource("101")),
        ]
        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KUBERNETES_API_URL": "https://cluster.example",
                        "KUBERNETES_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.kubernetes.open_no_redirect",
                    side_effect=responses,
                ) as request,
            ):
                session = begin_step_contracts(
                    _kubernetes_step(),
                    _kubernetes_payload(),
                    _paths(Path(tmp)),
                    observation_policy=AuthorityObservationPolicy("none", "fail"),
                )
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "fail"),
                    completion_floor=datetime.now(timezone.utc).isoformat(),
                )

        self.assertEqual(receipt.interval_status, "stable")
        self.assertEqual(receipt.completion_status, "fresh")
        self.assertEqual(receipt.decision, "allow")
        self.assertEqual(receipt.before.token, "resourceVersion:101")
        self.assertEqual(receipt.after.token, "resourceVersion:101")
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("secret-token", json.dumps(receipt.to_evidence()))

    def test_kubernetes_resource_version_detects_reconverged_mutation(self) -> None:
        responses = [
            _Response(body=_kubernetes_resource("101")),
            _Response(body=_kubernetes_resource("103")),
        ]
        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KUBERNETES_API_URL": "https://cluster.example",
                        "KUBERNETES_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.kubernetes.open_no_redirect",
                    side_effect=responses,
                ),
            ):
                session = begin_step_contracts(
                    _kubernetes_step(),
                    _kubernetes_payload(),
                    _paths(Path(tmp)),
                    observation_policy=AuthorityObservationPolicy("none", "fail"),
                )
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "fail"),
                    completion_floor=datetime.now(timezone.utc).isoformat(),
                )

        self.assertEqual(receipt.interval_status, "drifted")
        self.assertEqual(receipt.completion_status, "fresh")
        self.assertEqual(receipt.decision, "deny")
        self.assertIn("changed during the operation", receipt.result)

    def test_kubernetes_adapter_exercises_reconverged_drift_over_http(self) -> None:
        resources = [
            _kubernetes_resource("101"),
            _kubernetes_resource("103"),
        ]

        class Handler(BaseHTTPRequestHandler):
            request_count = 0

            def do_GET(self) -> None:
                if self.path != "/api/v1/namespaces/platform/configmaps/change-authority":
                    self.send_error(404)
                    return
                if self.headers.get("Authorization") != "Bearer secret-token":
                    self.send_error(401)
                    return
                index = min(self.__class__.request_count, len(resources) - 1)
                body = resources[index]
                self.__class__.request_count += 1
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}"
            with TemporaryDirectory() as tmp, patch.dict(
                os.environ,
                {
                    "KUBERNETES_API_URL": endpoint,
                    "KUBERNETES_API_TOKEN": "secret-token",
                },
                clear=True,
            ):
                session = begin_step_contracts(
                    _kubernetes_step(),
                    _kubernetes_payload(),
                    _paths(Path(tmp)),
                    observation_policy=AuthorityObservationPolicy("none", "fail"),
                )
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "fail"),
                    completion_floor=datetime.now(timezone.utc).isoformat(),
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(Handler.request_count, 2)
        self.assertEqual(receipt.interval_status, "drifted")
        self.assertEqual(receipt.completion_status, "fresh")
        self.assertEqual(receipt.decision, "deny")

    def test_kubernetes_resource_replacement_is_drift(self) -> None:
        responses = [
            _Response(body=_kubernetes_resource("101", uid="uid-before")),
            _Response(body=_kubernetes_resource("103", uid="uid-after")),
        ]
        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KUBERNETES_API_URL": "https://cluster.example",
                        "KUBERNETES_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.kubernetes.open_no_redirect",
                    side_effect=responses,
                ),
            ):
                session = begin_step_contracts(
                    _kubernetes_step(),
                    _kubernetes_payload(),
                    _paths(Path(tmp)),
                    observation_policy=AuthorityObservationPolicy("none", "fail"),
                )
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "fail"),
                    completion_floor=datetime.now(timezone.utc).isoformat(),
                )

        self.assertEqual(receipt.interval_status, "drifted")
        self.assertEqual(receipt.decision, "deny")
        self.assertIn("replaced", receipt.result)

    def test_kubernetes_older_completion_revision_is_stale(self) -> None:
        responses = [
            _Response(body=_kubernetes_resource("103")),
            _Response(body=_kubernetes_resource("101")),
        ]
        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KUBERNETES_API_URL": "https://cluster.example",
                        "KUBERNETES_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.kubernetes.open_no_redirect",
                    side_effect=responses,
                ),
            ):
                session = begin_step_contracts(
                    _kubernetes_step(),
                    _kubernetes_payload(),
                    _paths(Path(tmp)),
                    observation_policy=AuthorityObservationPolicy("none", "fail"),
                )
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "fail"),
                    completion_floor=datetime.now(timezone.utc).isoformat(),
                )

        self.assertEqual(receipt.interval_status, "unverifiable")
        self.assertEqual(receipt.completion_status, "stale")
        self.assertEqual(receipt.decision, "deny")

    def test_kubernetes_expected_write_is_rejected_before_dispatch(self) -> None:
        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KUBERNETES_API_URL": "https://cluster.example",
                        "KUBERNETES_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.kubernetes.open_no_redirect",
                    return_value=_Response(body=_kubernetes_resource("101")),
                ) as request,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "cannot establish the interval evidence required by policy",
                ):
                    begin_step_contracts(
                        _kubernetes_step(expected_change="operation"),
                        _kubernetes_payload(),
                        _paths(Path(tmp)),
                        observation_policy=AuthorityObservationPolicy(
                            "operation",
                            "fail",
                        ),
                    )

        request.assert_called_once()

    def test_kubernetes_rejects_collection_path(self) -> None:
        payload = _kubernetes_payload()
        payload["authorities"]["change_control"]["config"]["resource_path"] = (
            "/api/v1/namespaces/platform/configmaps"
        )
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "must identify one Kubernetes"):
                enforce_step_contracts(
                    _kubernetes_step(),
                    payload,
                    _paths(Path(tmp)),
                )

    def test_kubernetes_rejects_plain_http_for_non_loopback_endpoint(self) -> None:
        payload = _kubernetes_payload()
        payload["authorities"]["change_control"]["config"]["endpoint"] = (
            "http://cluster.example"
        )
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "must use https"):
                enforce_step_contracts(
                    _kubernetes_step(),
                    payload,
                    _paths(Path(tmp)),
                )

    def test_kubernetes_rejects_mismatched_resource_identity(self) -> None:
        resource = json.loads(_kubernetes_resource("101"))
        resource["metadata"]["name"] = "another-authority"
        with TemporaryDirectory() as tmp:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KUBERNETES_API_URL": "https://cluster.example",
                        "KUBERNETES_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.kubernetes.open_no_redirect",
                    return_value=_Response(body=json.dumps(resource).encode("utf-8")),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    enforce_step_contracts(
                        _kubernetes_step(),
                        _kubernetes_payload(),
                        _paths(Path(tmp)),
                    )

    def test_nautobot_detects_changed_snapshot_when_no_change_is_expected(self) -> None:
        api_reads = 0

        def respond(request, **kwargs):
            nonlocal api_reads
            del kwargs
            if request.full_url.endswith("/health/"):
                return _Response()
            api_reads += 1
            prefix_id = f"prefix-{api_reads}"
            return _Response(
                headers={"API-Version": "2.4"},
                body=json.dumps(
                    {"count": 1, "results": [{"id": prefix_id}]}
                ).encode("utf-8"),
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.dict(
                    os.environ,
                    {
                        "NAUTOBOT_API_URL": "https://nautobot.example/api/",
                        "NAUTOBOT_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.nautobot.open_no_redirect",
                    side_effect=respond,
                ),
            ):
                session = begin_step_contracts(
                    _canonical_step(),
                    _canonical_payload("nautobot"),
                    _paths(root),
                )
                floor = datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                ).replace("+00:00", "Z")
                receipt = complete_step_authority(
                    session,
                    AuthorityObservationPolicy("none", "record"),
                    completion_floor=floor,
                )

        self.assertEqual(receipt.interval_status, "drifted")
        self.assertEqual(receipt.completion_status, "fresh")
        self.assertEqual(receipt.decision, "deny")

    def test_nautobot_rejects_inline_token_configuration(self) -> None:
        payload = _canonical_payload("nautobot", {"token": "inline-secret"})
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "unknown configuration keys: token") as caught:
                enforce_step_contracts(
                    _canonical_step(),
                    payload,
                    _paths(Path(tmp)),
                )

        self.assertNotIn("inline-secret", str(caught.exception))

    def test_unreachable_nautobot_blocks_operation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.dict(
                    os.environ,
                    {
                        "NAUTOBOT_API_URL": "https://nautobot.example",
                        "NAUTOBOT_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.nautobot.open_no_redirect",
                    side_effect=URLError("offline"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "not ready.*unreachable"):
                    enforce_step_contracts(
                        _canonical_step(),
                        _canonical_payload("nautobot"),
                        _paths(root),
                    )

    def test_nautobot_rejects_non_api_success_response(self) -> None:
        def respond(request, **kwargs):
            del kwargs
            if request.full_url.endswith("/health/"):
                return _Response()
            return _Response(body=b"<html>sign in</html>")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.dict(
                    os.environ,
                    {
                        "NAUTOBOT_API_URL": "https://nautobot.example",
                        "NAUTOBOT_API_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "hyops.authority.providers.nautobot.open_no_redirect",
                    side_effect=respond,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "invalid JSON response"):
                    enforce_step_contracts(
                        _canonical_step(),
                        _canonical_payload("nautobot"),
                        _paths(root),
                    )

    def test_missing_nautobot_configuration_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "missing required Nautobot configuration"):
                enforce_step_contracts(
                    _canonical_step(),
                    _canonical_payload("nautobot"),
                    _paths(Path(tmp)),
                )

    def test_missing_binding_and_unknown_provider_fail_closed(self) -> None:
        context = AuthorityContext(
            runtime_root=Path("/tmp/runtime"),
            state_root=Path("/tmp/runtime/state"),
            env={},
        )
        resolver = AuthorityResolver(default_authority_registry())
        requirement = AuthorityRequirement("primary_ipam", "inventory_ipam")
        with self.assertRaisesRegex(ValueError, "missing authority binding"):
            resolver.enforce(requirement, {}, context)
        declaration = AuthorityDeclaration(
            "primary_ipam",
            "inventory_ipam",
            "unknown_cmdb",
        )
        with self.assertRaisesRegex(ValueError, "unknown authority provider 'unknown_cmdb'"):
            resolver.enforce(requirement, {"primary_ipam": declaration}, context)

    def test_capability_mismatch_is_rejected(self) -> None:
        resolver = AuthorityResolver(default_authority_registry())
        context = AuthorityContext(Path("/tmp"), Path("/tmp/state"), {})
        declaration = AuthorityDeclaration("primary_ipam", "asset_inventory", "netbox")
        with self.assertRaisesRegex(ValueError, "authority capability mismatch"):
            resolver.enforce(
                AuthorityRequirement("primary_ipam", "inventory_ipam"),
                {"primary_ipam": declaration},
                context,
            )

    def test_stale_netbox_state_is_rejected_when_freshness_is_bounded(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_netbox_state(root, updated_at=old)
            payload = _canonical_payload("netbox", {"max_state_age_s": 60})
            with patch.dict(
                os.environ,
                {"HYOPS_NETBOX_AUTHORITY_ROOT": str(root)},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "state is stale"):
                    enforce_step_contracts(_canonical_step(), payload, _paths(root))

    def test_generic_executor_has_no_provider_runtime_branch(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "blueprint" / "contracts.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("runtime.netbox_env", source)
        self.assertNotIn("NetBoxAuthorityProvider", source)
        self.assertNotIn("NautobotAuthorityProvider", source)


class AuthoritySchemaTests(unittest.TestCase):
    def _spec(self) -> dict:
        return {
            "api_version": "hybridops/v1",
            "kind": "BlueprintSpec",
            "blueprint_ref": "test/authority@v1",
            "mode": "authoritative",
            "authorities": {
                "primary_ipam": {
                    "capability": "inventory_ipam",
                    "provider": "nautobot",
                }
            },
            "steps": [
                {
                    "id": "operation",
                    "module_ref": "test/module",
                    "contracts": {
                        "addressing_mode": "ipam",
                        "requires_authority": {
                            "ref": "primary_ipam",
                            "capability": "inventory_ipam",
                        },
                    },
                }
            ],
        }

    def test_canonical_and_legacy_forms_validate(self) -> None:
        canonical = validate_blueprint(self._spec(), Path("blueprint.yml"))
        self.assertEqual(canonical["authorities"]["primary_ipam"]["provider"], "nautobot")

        legacy = self._spec()
        legacy.pop("authorities")
        legacy["policy"] = {"ipam_authority": "netbox"}
        legacy["steps"][0]["contracts"]["requires_authority"] = "netbox"
        validated = validate_blueprint(legacy, Path("blueprint.yml"))
        self.assertEqual(
            validated["steps"][0]["contracts"]["requires_authority"],
            "netbox",
        )

    def test_authority_observation_policy_validates(self) -> None:
        spec = self._spec()
        spec["steps"][0]["contracts"]["authority_observation"] = {
            "expected_change": "operation",
        }

        validated = validate_blueprint(spec, Path("blueprint.yml"))

        self.assertEqual(
            validated["steps"][0]["contracts"]["authority_observation"],
            {"expected_change": "operation", "on_unverifiable": "fail"},
        )

    def test_authority_observation_requires_binding_and_valid_policy(self) -> None:
        missing = self._spec()
        missing["steps"][0]["contracts"]["requires_authority"] = "none"
        missing["steps"][0]["contracts"]["addressing_mode"] = "static"
        missing["steps"][0]["contracts"]["authority_observation"] = {
            "expected_change": "none"
        }
        with self.assertRaisesRegex(ValueError, "requires an authority binding"):
            validate_blueprint(missing, Path("blueprint.yml"))

        invalid = self._spec()
        invalid["steps"][0]["contracts"]["authority_observation"] = {
            "expected_change": "unknown"
        }
        with self.assertRaisesRegex(ValueError, "must be one of: none, operation"):
            validate_blueprint(invalid, Path("blueprint.yml"))

    def test_missing_binding_and_capability_mismatch_are_rejected(self) -> None:
        missing = self._spec()
        missing["authorities"] = {}
        with self.assertRaisesRegex(ValueError, "missing authority binding"):
            validate_blueprint(missing, Path("blueprint.yml"))

        mismatch = self._spec()
        mismatch["authorities"]["primary_ipam"]["capability"] = "asset_inventory"
        with self.assertRaisesRegex(ValueError, "authority capability mismatch"):
            validate_blueprint(mismatch, Path("blueprint.yml"))

    def test_json_schema_exposes_canonical_and_legacy_forms(self) -> None:
        schema_path = (
            Path(__file__).resolve().parents[3]
            / "modules"
            / "_shared"
            / "contracts"
            / "blueprint-spec.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn("authorities", schema["properties"])
        requirement = schema["$defs"]["step"]["properties"]["contracts"][
            "properties"
        ]["requires_authority"]
        legacy_pattern = requirement["oneOf"][0]["pattern"]
        self.assertIsNotNone(re.fullmatch(legacy_pattern, "netbox"))
        self.assertEqual(
            requirement["oneOf"][1]["$ref"],
            "#/$defs/authorityRequirement",
        )
        observation = schema["$defs"]["step"]["properties"]["contracts"][
            "properties"
        ]["authority_observation"]
        self.assertEqual(observation["$ref"], "#/$defs/authorityObservation")
        observation_binding = schema["$defs"]["step"]["properties"]["contracts"][
            "allOf"
        ][0]
        self.assertEqual(
            observation_binding["if"]["required"],
            ["authority_observation"],
        )
        self.assertEqual(
            observation_binding["then"]["required"],
            ["requires_authority"],
        )
        self.assertEqual(
            observation_binding["then"]["properties"]["requires_authority"]["not"],
            {"const": "none"},
        )


if __name__ == "__main__":
    unittest.main()
