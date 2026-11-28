from __future__ import annotations

import copy
import math
import unittest
from dataclasses import fields

from hyops.continuity.api.models import (
    ApiPolicy,
    ApiResource,
    ApiSpec,
    ApiStage,
    ApiStatus,
    ApiWorkload,
)
from hyops.continuity.api.v1alpha1 import ApiValidationError, decode, encode

_DIGEST_A = f"sha256:{'a' * 64}"
_DIGEST_B = f"sha256:{'b' * 64}"
_DIGEST_C = f"sha256:{'c' * 64}"


def _valid_payload() -> dict:
    return {
        "apiVersion": "continuity.hybridops.tech/v1alpha1",
        "kind": "ContinuityContract",
        "metadata": {
            "name": "contract-one",
            "namespace": "continuity-system",
            "uid": "2e2ae2a0-1456-43dd-bc71-427c6a37cb7d",
            "generation": 3,
            "resourceVersion": "19",
            "labels": {"continuity.hybridops.tech/workload": "conformance"},
            "annotations": {"example": "retained"},
        },
        "spec": {
            "workload": {
                "name": "conformance-workload",
                "revision": "v1.0.0",
                "digest": _DIGEST_A,
                "ref": {
                    "apiGroup": "",
                    "kind": "ConfigMap",
                    "name": "conformance-workload",
                },
            },
            "policy": {
                "failureAction": "Recover",
                "unverifiableAction": "Block",
                "terminalEvidence": "Required",
            },
            "authorities": [
                {
                    "name": "release-authority",
                    "capability": "release",
                    "provider": "conformance",
                    "compatibility": False,
                    "parametersRef": {
                        "apiGroup": "",
                        "kind": "Secret",
                        "name": "release-authority",
                    },
                }
            ],
            "recoverySets": [
                {
                    "name": "workload-state",
                    "producer": {
                        "stage": "prepare",
                        "evidence": "prepared-state",
                        "role": "recovery",
                    },
                }
            ],
            "stages": [
                {
                    "id": "prepare",
                    "adapterRef": {"name": "conformance"},
                    "operation": "prepare",
                    "requires": [],
                    "parametersRef": {
                        "apiGroup": "",
                        "kind": "ConfigMap",
                        "name": "prepare-parameters",
                    },
                    "inputBindings": [],
                    "publish": ["prepared-output"],
                    "recoverySets": [],
                    "recoveryOperation": "remove",
                },
                {
                    "id": "release",
                    "adapterRef": {"name": "conformance"},
                    "operation": "release",
                    "requires": ["prepare"],
                    "inputBindings": [
                        {
                            "name": "prepared-input",
                            "stage": "prepare",
                            "output": "prepared-output",
                        }
                    ],
                    "publish": [],
                    "recoverySets": ["workload-state"],
                    "authorityRef": "release-authority",
                },
            ],
        },
        "status": {
            "observedGeneration": 3,
            "phase": "Succeeded",
            "conditions": [
                {
                    "type": "continuity.hybridops.tech/Ready",
                    "status": "True",
                    "observedGeneration": 3,
                    "lastTransitionTime": "2026-11-28T10:15:30Z",
                    "reason": "ContractCompleted",
                    "message": "continuity contract completed",
                }
            ],
            "recoverySets": [
                {
                    "name": "workload-state",
                    "evidence": "prepared-state",
                    "role": "recovery",
                    "digest": _DIGEST_B,
                }
            ],
            "terminalEvidenceRef": {
                "apiGroup": "",
                "kind": "ConfigMap",
                "name": "contract-one-terminal",
                "digest": _DIGEST_C,
            },
        },
    }


def _minimal_payload() -> dict:
    return {
        "apiVersion": "continuity.hybridops.tech/v1alpha1",
        "kind": "ContinuityContract",
        "metadata": {"name": "minimal"},
        "spec": {
            "workload": {
                "name": "workload",
                "revision": "v1",
                "digest": _DIGEST_A,
            },
            "stages": [
                {
                    "id": "prepare",
                    "adapterRef": {"name": "conformance"},
                    "operation": "prepare",
                }
            ],
        },
    }


class V1Alpha1CodecTests(unittest.TestCase):
    def assert_failure(
        self,
        payload: dict,
        reason_code: str,
        path: str,
    ) -> None:
        with self.assertRaises(ApiValidationError) as raised:
            decode(payload)
        self.assertEqual(raised.exception.reason_code, reason_code)
        self.assertEqual(raised.exception.path, path)

    def test_round_trip_preserves_kubernetes_metadata(self) -> None:
        payload = _valid_payload()

        encoded = encode(decode(payload))

        self.assertEqual(encoded, payload)
        self.assertEqual(encode(decode(encoded)), encoded)

    def test_hub_resource_is_version_neutral(self) -> None:
        self.assertEqual(
            [item.name for item in fields(ApiResource)],
            ["metadata", "spec", "status"],
        )

    def test_defaults_are_stable(self) -> None:
        resource = decode(_minimal_payload())

        self.assertEqual(resource.metadata.namespace, "default")
        self.assertEqual(resource.spec.policy.failure_action, "Recover")
        self.assertEqual(resource.spec.policy.unverifiable_action, "Block")
        self.assertEqual(resource.spec.policy.terminal_evidence, "Required")
        self.assertEqual(resource.spec.authorities, ())
        self.assertEqual(resource.spec.recovery_sets, ())
        self.assertIsNone(resource.status)
        self.assertEqual(resource.spec.stages[0].requires, ())
        self.assertEqual(resource.spec.stages[0].publish, frozenset())

    def test_metadata_is_deeply_immutable_and_unaliased(self) -> None:
        payload = _valid_payload()
        resource = decode(payload)
        payload["metadata"]["labels"]["new"] = "source-mutated"

        self.assertNotIn("new", resource.metadata.extra["labels"])
        with self.assertRaises(TypeError):
            resource.metadata.extra["labels"]["new"] = "forbidden"

    def test_metadata_rejects_non_json_values(self) -> None:
        for value in ({"mutable"}, math.inf, object()):
            with self.subTest(value=type(value).__name__):
                payload = _minimal_payload()
                payload["metadata"]["invalid"] = value
                self.assert_failure(payload, "InvalidMetadata", "$.metadata")

    def test_rejects_invalid_root_and_shape_fields(self) -> None:
        cases: list[tuple[str, object, str, str]] = [
            (
                "apiVersion",
                "continuity.hybridops.tech/v2",
                "UnsupportedAPIVersion",
                "$.apiVersion",
            ),
            ("kind", "Contract", "InvalidKind", "$.kind"),
        ]
        for field, value, reason, path in cases:
            with self.subTest(field=field):
                payload = _minimal_payload()
                payload[field] = value
                self.assert_failure(payload, reason, path)

        payload = _minimal_payload()
        payload["unknown"] = True
        self.assert_failure(payload, "UnknownField", "$")

        payload = _minimal_payload()
        payload["spec"]["stages"] = {}
        self.assert_failure(payload, "InvalidType", "$.spec.stages")

    def test_rejects_invalid_workload_identity(self) -> None:
        cases = [
            ("name", " leading", "InvalidValue", "$.spec.workload.name"),
            ("name", "line\nbreak", "InvalidValue", "$.spec.workload.name"),
            ("name", "x" * 254, "InvalidValue", "$.spec.workload.name"),
            (
                "revision",
                "line\rbreak",
                "InvalidValue",
                "$.spec.workload.revision",
            ),
            ("revision", "x" * 257, "InvalidValue", "$.spec.workload.revision"),
            ("digest", "sha256:bad", "InvalidDigest", "$.spec.workload.digest"),
        ]
        for field, value, reason, path in cases:
            with self.subTest(field=field, value=str(value)[:20]):
                payload = _minimal_payload()
                payload["spec"]["workload"][field] = value
                self.assert_failure(payload, reason, path)

    def test_rejects_invalid_references(self) -> None:
        for field, value, path in (
            ("apiGroup", "invalid..group", "$.spec.workload.ref.apiGroup"),
            ("apiGroup", "a" * 64, "$.spec.workload.ref.apiGroup"),
            ("kind", "config-map", "$.spec.workload.ref.kind"),
            ("name", "Invalid_Name", "$.spec.workload.ref.name"),
            ("name", "a" * 64, "$.spec.workload.ref.name"),
        ):
            with self.subTest(field=field):
                payload = _minimal_payload()
                payload["spec"]["workload"]["ref"] = {
                    "apiGroup": "",
                    "kind": "ConfigMap",
                    "name": "workload",
                }
                payload["spec"]["workload"]["ref"][field] = value
                self.assert_failure(payload, "InvalidReference", path)

    def test_rejects_duplicate_set_values(self) -> None:
        for field, value in (
            ("publish", ["result", "result"]),
            ("recoverySets", ["state", "state"]),
        ):
            with self.subTest(field=field):
                payload = _minimal_payload()
                payload["spec"]["stages"][0][field] = value
                self.assert_failure(
                    payload,
                    "DuplicateValue",
                    f"$.spec.stages[0].{field}",
                )

    def test_rejects_duplicate_named_values(self) -> None:
        cases = []

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"].append(copy.deepcopy(payload["spec"]["stages"][0]))
        cases.append((payload, "DuplicateStage", "$.spec.stages"))

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["authorities"].append(
            copy.deepcopy(payload["spec"]["authorities"][0])
        )
        cases.append((payload, "DuplicateAuthority", "$.spec.authorities"))

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["recoverySets"].append(
            copy.deepcopy(payload["spec"]["recoverySets"][0])
        )
        cases.append((payload, "DuplicateRecoverySet", "$.spec.recoverySets"))

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"][1]["requires"] = ["prepare", "prepare"]
        cases.append(
            (
                payload,
                "DuplicateDependency",
                "$.spec.stages[release].requires",
            )
        )

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"][1]["inputBindings"].append(
            copy.deepcopy(payload["spec"]["stages"][1]["inputBindings"][0])
        )
        cases.append(
            (
                payload,
                "DuplicateInputBinding",
                "$.spec.stages[release].inputBindings",
            )
        )

        payload = _valid_payload()
        payload["status"]["recoverySets"].append(
            copy.deepcopy(payload["status"]["recoverySets"][0])
        )
        cases.append((payload, "DuplicateRecoverySet", "$.status.recoverySets"))

        for payload, reason, path in cases:
            with self.subTest(reason=reason, path=path):
                self.assert_failure(payload, reason, path)

    def test_rejects_invalid_dependency_graphs(self) -> None:
        payload = _minimal_payload()
        payload["spec"]["stages"][0]["requires"] = ["missing"]
        self.assert_failure(
            payload,
            "UnknownDependency",
            "$.spec.stages[prepare].requires",
        )

        payload = _minimal_payload()
        payload["spec"]["stages"][0]["requires"] = ["prepare"]
        self.assert_failure(
            payload,
            "DependencyCycle",
            "$.spec.stages[prepare].requires",
        )

        payload = _minimal_payload()
        payload["spec"]["stages"].extend(
            [
                {
                    "id": "second",
                    "adapterRef": {"name": "conformance"},
                    "operation": "prepare",
                    "requires": ["third"],
                },
                {
                    "id": "third",
                    "adapterRef": {"name": "conformance"},
                    "operation": "prepare",
                    "requires": ["second"],
                },
            ]
        )
        self.assert_failure(payload, "DependencyCycle", "$.spec.stages")

    def test_rejects_unordered_or_unpublished_input_bindings(self) -> None:
        payload = _valid_payload()
        payload.pop("status")
        release = payload["spec"]["stages"][1]
        release["requires"] = []
        self.assert_failure(
            payload,
            "UnorderedInputBinding",
            "$.spec.stages[release].inputBindings",
        )

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"][0]["publish"] = []
        self.assert_failure(
            payload,
            "UnpublishedInputBinding",
            "$.spec.stages[release].inputBindings",
        )

    def test_accepts_bindings_from_transitive_dependencies(self) -> None:
        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"].insert(
            1,
            {
                "id": "transform",
                "adapterRef": {"name": "conformance"},
                "operation": "transform",
                "requires": ["prepare"],
                "publish": ["transformed-output"],
            },
        )
        payload["spec"]["stages"][2]["requires"] = ["transform"]

        resource = decode(payload)

        self.assertEqual(resource.spec.stages[2].input_bindings[0].stage, "prepare")
        self.assertEqual(
            resource.spec.stages[2].recovery_sets,
            frozenset({"workload-state"}),
        )

    def test_rejects_unbound_recovery_and_authority_references(self) -> None:
        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"][1]["recoverySets"] = ["unknown"]
        self.assert_failure(
            payload,
            "UnknownRecoverySet",
            "$.spec.stages[release].recoverySets",
        )

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["recoverySets"][0]["producer"]["stage"] = "unknown"
        self.assert_failure(
            payload,
            "UnknownRecoveryProducer",
            "$.spec.recoverySets[workload-state]",
        )

        payload = _valid_payload()
        payload.pop("status")
        release = payload["spec"]["stages"][1]
        release["requires"] = []
        release["inputBindings"] = []
        self.assert_failure(
            payload,
            "UnorderedRecoverySet",
            "$.spec.stages[release].recoverySets",
        )

        payload = _valid_payload()
        payload.pop("status")
        payload["spec"]["stages"][1]["authorityRef"] = "unknown"
        self.assert_failure(
            payload,
            "UnknownAuthority",
            "$.spec.stages[release].authorityRef",
        )

    def test_rejects_invalid_condition_values(self) -> None:
        cases = [
            ("type", "a..b/Ready", "$.status.conditions[0].type"),
            ("reason", "bad reason", "$.status.conditions[0].reason"),
            ("message", None, "$.status.conditions[0].message"),
            (
                "lastTransitionTime",
                "2026-11-28 10:15:30+00:00",
                "$.status.conditions[0].lastTransitionTime",
            ),
        ]
        for field, value, path in cases:
            with self.subTest(field=field):
                payload = _valid_payload()
                payload["status"]["conditions"][0][field] = value
                reason = "InvalidType" if field == "message" else "InvalidCondition"
                self.assert_failure(payload, reason, path)

    def test_rejects_invalid_status_generation_and_duplicates(self) -> None:
        payload = _valid_payload()
        payload["status"]["observedGeneration"] = 4
        self.assert_failure(
            payload,
            "InvalidStatus",
            "$.status.observedGeneration",
        )

        payload = _valid_payload()
        payload["status"]["conditions"][0]["observedGeneration"] = 4
        self.assert_failure(
            payload,
            "InvalidCondition",
            "$.status.conditions[continuity.hybridops.tech/Ready].observedGeneration",
        )

        payload = _valid_payload()
        payload["status"]["conditions"].append(
            copy.deepcopy(payload["status"]["conditions"][0])
        )
        self.assert_failure(payload, "DuplicateCondition", "$.status.conditions")

    def test_terminal_status_must_be_current_and_evidenced(self) -> None:
        payload = _valid_payload()
        payload["status"]["observedGeneration"] = 2
        payload["status"]["conditions"][0]["observedGeneration"] = 2
        self.assert_failure(
            payload,
            "StaleTerminalStatus",
            "$.status.observedGeneration",
        )

        payload = _valid_payload()
        payload["status"].pop("terminalEvidenceRef")
        self.assert_failure(
            payload,
            "InvalidTerminalStatus",
            "$.status.terminalEvidenceRef",
        )

        payload = _valid_payload()
        payload["status"]["phase"] = "Running"
        self.assert_failure(
            payload,
            "InvalidTerminalStatus",
            "$.status.terminalEvidenceRef",
        )

    def test_status_recovery_sets_must_match_the_contract(self) -> None:
        payload = _valid_payload()
        payload["status"]["recoverySets"][0]["name"] = "unknown"
        self.assert_failure(
            payload,
            "UnknownRecoverySet",
            "$.status.recoverySets[unknown]",
        )

        payload = _valid_payload()
        payload["status"]["recoverySets"][0]["role"] = "other"
        self.assert_failure(
            payload,
            "RecoverySetMismatch",
            "$.status.recoverySets[workload-state]",
        )

        payload = _valid_payload()
        payload["status"]["recoverySets"] = []
        self.assert_failure(
            payload,
            "IncompleteRecoverySetStatus",
            "$.status.recoverySets",
        )

    def test_direct_construction_rejects_mutable_collections(self) -> None:
        stage = ApiStage(
            id="prepare",
            adapter="conformance",
            operation="prepare",
        )
        workload = ApiWorkload("workload", "v1", _DIGEST_A)

        with self.assertRaises(TypeError):
            ApiStage("bad", "conformance", "prepare", requires=[])
        with self.assertRaises(TypeError):
            ApiSpec(workload, ApiPolicy(), stages=[stage])
        with self.assertRaises(TypeError):
            ApiStatus(conditions=[])

    def test_encode_rejects_malformed_direct_construction(self) -> None:
        resource = ApiResource(metadata=None, spec=None)

        self.assert_failure_from_encode(resource, "InvalidResource", "$")

    def assert_failure_from_encode(
        self,
        resource: ApiResource,
        reason_code: str,
        path: str,
    ) -> None:
        with self.assertRaises(ApiValidationError) as raised:
            encode(resource)
        self.assertEqual(raised.exception.reason_code, reason_code)
        self.assertEqual(raised.exception.path, path)


if __name__ == "__main__":
    unittest.main()
