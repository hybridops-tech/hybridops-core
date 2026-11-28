from __future__ import annotations

import copy
import math
import unittest
from dataclasses import fields, replace

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
        "apiVersion": "continuity.hyopsproject.github.io/v1alpha1",
        "kind": "ContinuityContract",
        "metadata": {
            "name": "contract-one",
            "namespace": "continuity-system",
            "uid": "2e2ae2a0-1456-43dd-bc71-427c6a37cb7d",
            "generation": 3,
            "resourceVersion": "19",
            "labels": {"continuity.hyopsproject.github.io/workload": "conformance"},
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
                    "destructive": True,
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
                    "type": "continuity.hyopsproject.github.io/Ready",
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
        "apiVersion": "continuity.hyopsproject.github.io/v1alpha1",
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

    def test_extra_metadata_cannot_supply_typed_identity(self) -> None:
        resource = decode(_valid_payload())
        for key in ("name", "namespace", "uid", "generation"):
            with self.subTest(key=key):
                metadata = replace(
                    resource.metadata,
                    uid="",
                    generation=0,
                    extra={key: getattr(resource.metadata, key)},
                )
                self.assert_failure_from_encode(
                    replace(resource, metadata=metadata),
                    "InvalidMetadata",
                    "$.metadata",
                )

    def test_encode_validates_metadata_before_omitting_defaults(self) -> None:
        resource = decode(_minimal_payload())
        self.assertEqual(
            encode(resource)["metadata"], {"name": "minimal", "namespace": "default"}
        )
        for field, value, reason in (
            ("uid", None, "InvalidMetadata"),
            ("uid", False, "InvalidMetadata"),
            ("generation", None, "InvalidType"),
            ("generation", False, "InvalidType"),
            ("generation", 0.0, "InvalidType"),
        ):
            with self.subTest(field=field, value=value):
                metadata = replace(resource.metadata, **{field: value})
                self.assert_failure_from_encode(
                    replace(resource, metadata=metadata), reason, f"$.metadata.{field}"
                )

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

    def test_kubernetes_collections_are_canonical(self) -> None:
        payload = _valid_payload()
        payload["spec"]["authorities"].append(
            {
                "name": "archive-authority",
                "capability": "archive",
                "provider": "conformance",
            }
        )
        payload["spec"]["recoverySets"].append(
            {
                "name": "archive-state",
                "producer": {
                    "stage": "prepare",
                    "evidence": "archive-evidence",
                    "role": "recovery",
                },
            }
        )
        payload["spec"]["stages"][1]["publish"] = ["released-output"]
        payload["spec"]["stages"][1]["recoverySets"].append("archive-state")
        payload["spec"]["stages"].append(
            {
                "id": "verify",
                "adapterRef": {"name": "conformance"},
                "operation": "verify",
                "requires": ["release", "prepare"],
                "inputBindings": [
                    {
                        "name": "released-input",
                        "stage": "release",
                        "output": "released-output",
                    },
                    {
                        "name": "prepared-input",
                        "stage": "prepare",
                        "output": "prepared-output",
                    },
                ],
                "publish": ["z-output", "a-output"],
                "recoverySets": ["workload-state", "archive-state"],
                "authorityRef": "archive-authority",
            }
        )
        payload["status"]["conditions"].append(
            {
                "type": "continuity.hyopsproject.github.io/Admitted",
                "status": "True",
                "observedGeneration": 3,
                "lastTransitionTime": "2026-11-28T10:14:30Z",
                "reason": "ContractAdmitted",
                "message": "contract admitted",
            }
        )
        payload["status"]["recoverySets"].append(
            {
                "name": "archive-state",
                "evidence": "archive-evidence",
                "role": "recovery",
                "digest": _DIGEST_B,
            }
        )

        reordered = copy.deepcopy(payload)
        for field in ("authorities", "recoverySets", "stages"):
            reordered["spec"][field].reverse()
        for stage in reordered["spec"]["stages"]:
            for field in ("requires", "inputBindings", "publish", "recoverySets"):
                if field in stage:
                    stage[field].reverse()
        reordered["status"]["conditions"].reverse()
        reordered["status"]["recoverySets"].reverse()

        resource = decode(payload)
        reordered_resource = decode(reordered)
        encoded = encode(resource)

        self.assertEqual(reordered_resource, resource)
        self.assertEqual(encode(reordered_resource), encoded)
        self.assertEqual(
            [item["name"] for item in encoded["spec"]["authorities"]],
            ["archive-authority", "release-authority"],
        )
        self.assertEqual(
            [item["name"] for item in encoded["spec"]["recoverySets"]],
            ["archive-state", "workload-state"],
        )
        self.assertEqual(
            [item["id"] for item in encoded["spec"]["stages"]],
            ["prepare", "release", "verify"],
        )
        verify = encoded["spec"]["stages"][2]
        self.assertEqual(verify["requires"], ["prepare", "release"])
        self.assertEqual(
            [item["name"] for item in verify["inputBindings"]],
            ["prepared-input", "released-input"],
        )
        self.assertEqual(verify["publish"], ["a-output", "z-output"])
        self.assertEqual(
            verify["recoverySets"],
            ["archive-state", "workload-state"],
        )
        self.assertEqual(
            [item["type"] for item in encoded["status"]["conditions"]],
            [
                "continuity.hyopsproject.github.io/Admitted",
                "continuity.hyopsproject.github.io/Ready",
            ],
        )
        self.assertEqual(
            [item["name"] for item in encoded["status"]["recoverySets"]],
            ["archive-state", "workload-state"],
        )

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
                "continuity.hyopsproject.github.io/v2",
                "UnsupportedAPIVersion",
                "$.apiVersion",
            ),
            (
                "apiVersion",
                "continuity.hybridops.tech/v1alpha1",
                "UnsupportedAPIVersion",
                "$.apiVersion",
            ),
            ("kind", "Contract", "InvalidKind", "$.kind"),
        ]
        for field, value, reason, path in cases:
            with self.subTest(field=field, value=value):
                payload = _minimal_payload()
                payload[field] = value
                self.assert_failure(payload, reason, path)

        payload = _minimal_payload()
        payload["spec"]["stages"] = {}
        self.assert_failure(payload, "InvalidType", "$.spec.stages")

    def test_rejects_unknown_fields_at_every_strict_object_boundary(self) -> None:
        cases = [
            ("$", lambda item: item),
            ("$.spec", lambda item: item["spec"]),
            ("$.spec.workload", lambda item: item["spec"]["workload"]),
            ("$.spec.workload.ref", lambda item: item["spec"]["workload"]["ref"]),
            ("$.spec.policy", lambda item: item["spec"]["policy"]),
            ("$.spec.authorities[0]", lambda item: item["spec"]["authorities"][0]),
            (
                "$.spec.authorities[0].parametersRef",
                lambda item: item["spec"]["authorities"][0]["parametersRef"],
            ),
            ("$.spec.recoverySets[0]", lambda item: item["spec"]["recoverySets"][0]),
            (
                "$.spec.recoverySets[0].producer",
                lambda item: item["spec"]["recoverySets"][0]["producer"],
            ),
            ("$.spec.stages[0]", lambda item: item["spec"]["stages"][0]),
            (
                "$.spec.stages[0].adapterRef",
                lambda item: item["spec"]["stages"][0]["adapterRef"],
            ),
            (
                "$.spec.stages[0].parametersRef",
                lambda item: item["spec"]["stages"][0]["parametersRef"],
            ),
            (
                "$.spec.stages[1].inputBindings[0]",
                lambda item: item["spec"]["stages"][1]["inputBindings"][0],
            ),
            ("$.status", lambda item: item["status"]),
            ("$.status.conditions[0]", lambda item: item["status"]["conditions"][0]),
            (
                "$.status.recoverySets[0]",
                lambda item: item["status"]["recoverySets"][0],
            ),
            (
                "$.status.terminalEvidenceRef",
                lambda item: item["status"]["terminalEvidenceRef"],
            ),
        ]
        for path, select in cases:
            with self.subTest(path=path):
                payload = _valid_payload()
                select(payload)["unexpectedField"] = True
                self.assert_failure(payload, "UnknownField", path)

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
            ("name", "a" * 254, "$.spec.workload.ref.name"),
            ("name", "a.-b", "$.spec.workload.ref.name"),
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

    def test_kubernetes_subdomain_names_use_a_total_length_limit(self) -> None:
        for name in ("a" * 64, "a" * 253):
            with self.subTest(length=len(name)):
                payload = _valid_payload()
                payload["metadata"]["name"] = name
                payload["spec"]["workload"]["ref"]["name"] = name
                payload["status"]["terminalEvidenceRef"]["name"] = name
                self.assertEqual(encode(decode(payload)), payload)
        for name in ("a" * 254, "a..b", "a-.b", "a.-b", ".a", "a."):
            payload = _minimal_payload()
            payload["metadata"]["name"] = name
            self.assert_failure(payload, "InvalidMetadata", "$.metadata.name")
        payload = _minimal_payload()
        payload["metadata"]["namespace"] = "n" * 64
        self.assert_failure(payload, "InvalidMetadata", "$.metadata.namespace")

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
        release = next(stage for stage in resource.spec.stages if stage.id == "release")

        self.assertTrue(release.destructive)
        self.assertEqual(release.input_bindings[0].stage, "prepare")
        self.assertEqual(
            release.recovery_sets,
            frozenset({"workload-state"}),
        )

    def test_destructive_intent_is_explicit(self) -> None:
        payload = _minimal_payload()
        stage = payload["spec"]["stages"][0]
        stage["operation"] = "release"
        ordinary = decode(payload)
        self.assertIs(ordinary.spec.stages[0].destructive, False)
        stage["destructive"] = False
        self.assertEqual(decode(payload), ordinary)
        self.assertNotIn("destructive", encode(ordinary)["spec"]["stages"][0])

        for value in (None, 0, 1, "false", "true"):
            with self.subTest(value=value):
                stage["destructive"] = value
                self.assert_failure(
                    payload, "InvalidType", "$.spec.stages[0].destructive"
                )

    def test_destructive_stage_requires_authority_and_predecessor_recovery(
        self,
    ) -> None:
        for field, reason in (
            ("authorityRef", "MissingDestructiveAuthority"),
            ("recoverySets", "MissingRecoveryBarrier"),
        ):
            with self.subTest(field=field):
                payload = _valid_payload()
                del payload["spec"]["stages"][1][field]
                self.assert_failure(payload, reason, f"$.spec.stages[release].{field}")

        payload = _valid_payload()
        payload["spec"]["stages"][1]["recoverySets"] = []
        self.assert_failure(
            payload, "MissingRecoveryBarrier", "$.spec.stages[release].recoverySets"
        )

        payload = _valid_payload()
        payload["spec"]["recoverySets"][0]["producer"]["stage"] = "release"
        self.assert_failure(
            payload, "UnorderedRecoverySet", "$.spec.stages[release].recoverySets"
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
            "$.status.conditions[continuity.hyopsproject.github.io/Ready].observedGeneration",
        )

        payload = _valid_payload()
        payload["status"]["conditions"].append(
            copy.deepcopy(payload["status"]["conditions"][0])
        )
        self.assert_failure(payload, "DuplicateCondition", "$.status.conditions")

    def test_generation_fields_fit_signed_int64(self) -> None:
        payload = _valid_payload()
        maximum = (1 << 63) - 1
        fields = (
            (payload["metadata"], "generation", "$.metadata.generation"),
            (payload["status"], "observedGeneration", "$.status.observedGeneration"),
            (
                payload["status"]["conditions"][0],
                "observedGeneration",
                "$.status.conditions[0].observedGeneration",
            ),
        )
        for owner, key, _ in fields:
            owner[key] = maximum
        self.assertEqual(encode(decode(payload)), payload)
        for owner, key, path in fields:
            with self.subTest(path=path):
                owner[key] = maximum + 1
                self.assert_failure(payload, "InvalidValue", path)
                owner[key] = maximum

    def test_condition_zone_offsets(self) -> None:
        payload = _valid_payload()
        condition = payload["status"]["conditions"][0]
        for offset in ("+23:59", "-00:00"):
            with self.subTest(offset=offset):
                condition["lastTransitionTime"] = "2026-11-28T10:15:30" + offset
                self.assertEqual(encode(decode(payload)), payload)
        for offset in ("+00:60", "-20:75", "+24:00"):
            with self.subTest(offset=offset):
                condition["lastTransitionTime"] = "2026-11-28T10:15:30" + offset
                self.assert_failure(
                    payload,
                    "InvalidCondition",
                    "$.status.conditions[0].lastTransitionTime",
                )

    def test_terminal_status_must_be_current_and_evidenced(self) -> None:
        for phase in ("Succeeded", "Recovered", "Failed"):
            with self.subTest(phase=phase, state="valid"):
                payload = _valid_payload()
                payload["status"]["phase"] = phase
                self.assertEqual(decode(payload).status.phase, phase)

            with self.subTest(phase=phase, state="stale"):
                payload = _valid_payload()
                payload["status"]["phase"] = phase
                payload["status"]["observedGeneration"] = 2
                payload["status"]["conditions"][0]["observedGeneration"] = 2
                self.assert_failure(
                    payload,
                    "StaleTerminalStatus",
                    "$.status.observedGeneration",
                )

            for generation in (0, None):
                with self.subTest(phase=phase, generation=generation):
                    payload = _valid_payload()
                    payload["status"]["phase"] = phase
                    payload["status"]["conditions"] = []
                    for owner, field in (
                        (payload["metadata"], "generation"),
                        (payload["status"], "observedGeneration"),
                    ):
                        if generation is None:
                            owner.pop(field)
                        else:
                            owner[field] = generation
                    self.assert_failure(
                        payload, "StaleTerminalStatus", "$.status.observedGeneration"
                    )

            with self.subTest(phase=phase, state="unevidenced"):
                payload = _valid_payload()
                payload["status"]["phase"] = phase
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

    def test_success_requires_recovery_evidence_with_or_without_consumers(self) -> None:
        for consumer in (True, False):
            with self.subTest(consumer=consumer):
                payload = _valid_payload()
                if not consumer:
                    payload["spec"]["stages"].pop()
                self.assertEqual(decode(payload).status.phase, "Succeeded")

                payload["status"]["recoverySets"] = []
                self.assert_failure(
                    payload,
                    "IncompleteRecoverySetStatus",
                    "$.status.recoverySets",
                )

    def test_recovery_producers_cannot_have_multiple_identities(self) -> None:
        payload = _valid_payload()
        alias = copy.deepcopy(payload["spec"]["recoverySets"][0])
        alias["name"] = "workload-state-alias"
        payload["spec"]["recoverySets"].append(alias)
        identity = dict(payload["status"]["recoverySets"][0], name=alias["name"])
        payload["status"]["recoverySets"].append(identity)
        for role, digest in (
            ("recovery", _DIGEST_B),
            ("another-role", _DIGEST_B),
            ("recovery", _DIGEST_C),
        ):
            with self.subTest(role=role, digest=digest):
                alias["producer"]["role"] = identity["role"] = role
                identity["digest"] = digest
                self.assert_failure(
                    payload,
                    "DuplicateRecoveryProducer",
                    "$.spec.recoverySets[workload-state-alias].producer",
                )

        # Evidence names are scoped to their producer, not global.
        alias["producer"]["stage"] = "release"
        alias["producer"]["role"] = identity["role"] = "another-role"
        self.assertEqual(encode(decode(payload)), payload)

        # Multiple consumers can use the same declared recovery set.
        payload["spec"]["stages"].append(
            {
                "id": "verify",
                "adapterRef": {"name": "conformance"},
                "operation": "verify",
                "requires": ["prepare"],
                "recoverySets": ["workload-state"],
            }
        )
        spec = decode(payload).spec
        self.assertEqual(spec.stages[2].recovery_sets, {"workload-state"})
        self.assertEqual(
            spec.producer_evidence_by_stage(),
            {
                "prepare": {"prepared-state": "recovery"},
                "release": {"prepared-state": "another-role"},
                "verify": {},
            },
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

        resource = decode(_minimal_payload())
        for value, reason, path in (
            (0, "InvalidType", "$.spec.stages[0].destructive"),
            (
                True,
                "MissingDestructiveAuthority",
                "$.spec.stages[prepare].authorityRef",
            ),
        ):
            with self.subTest(destructive=value):
                stage = replace(resource.spec.stages[0], destructive=value)
                spec = replace(resource.spec, stages=(stage,))
                self.assert_failure_from_encode(
                    replace(resource, spec=spec), reason, path
                )

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
