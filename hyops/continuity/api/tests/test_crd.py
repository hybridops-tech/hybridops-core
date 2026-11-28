from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from hyops.continuity import validation as contract_validation
from hyops.continuity.api import (
    API_GROUP,
    API_KIND,
    AuthoritySpec,
    LocalObjectReference,
    v1alpha1 as codec,
)
from hyops.continuity.api.v1alpha1 import API_VERSION, decode, encode

_ROOT = Path(__file__).resolve().parents[4]
_CRD_PATH = (
    _ROOT
    / "config"
    / "crd"
    / "bases"
    / "continuity.hyopsproject.github.io_continuitycontracts.yaml"
)
_SAMPLE_PATH = _ROOT / "config" / "samples" / "continuity_v1alpha1_contract.yaml"


class ContinuityContractCrdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = yaml.safe_load(_CRD_PATH.read_text(encoding="utf-8"))
        cls.crd_spec = cls.document["spec"]
        cls.versions = cls.crd_spec["versions"]
        cls.version = cls.versions[0]
        cls.schema = cls.version["schema"]["openAPIV3Schema"]
        cls.spec_schema = cls.schema["properties"]["spec"]
        cls.status_schema = cls.schema["properties"]["status"]

    def test_resource_identity_and_status_subresource(self) -> None:
        self.assertEqual(self.document["apiVersion"], "apiextensions.k8s.io/v1")
        self.assertEqual(self.document["kind"], "CustomResourceDefinition")
        self.assertEqual(
            self.document["metadata"]["name"],
            f"continuitycontracts.{API_GROUP}",
        )
        self.assertEqual(self.crd_spec["group"], API_GROUP)
        self.assertEqual(self.crd_spec["scope"], "Namespaced")
        self.assertEqual(self.crd_spec["names"]["kind"], API_KIND)
        self.assertEqual(self.crd_spec["names"]["plural"], "continuitycontracts")
        self.assertEqual(len(self.versions), 1)
        self.assertEqual(self.version["name"], API_VERSION)
        self.assertTrue(self.version["served"])
        self.assertTrue(self.version["storage"])
        self.assertEqual(self.version["subresources"], {"status": {}})

    def test_schema_is_structural(self) -> None:
        self._assert_structural(self.schema, "schema")

    def test_only_unknown_root_fields_are_pruned(self) -> None:
        for path, schema in self._object_schemas(self.schema, "schema"):
            with self.subTest(path=path):
                self.assertEqual(
                    schema.get("x-kubernetes-preserve-unknown-fields", False),
                    path != "schema",
                )

    def _object_schemas(self, schema: dict, path: str):
        if schema.get("type") == "object":
            yield path, schema
        for name, child in schema.get("properties", {}).items():
            yield from self._object_schemas(child, f"{path}.{name}")
        if "items" in schema:
            yield from self._object_schemas(schema["items"], f"{path}[]")

    def _assert_structural(self, schema: dict, path: str) -> None:
        self.assertIn("type", schema, path)
        if "properties" in schema:
            self.assertEqual(schema["type"], "object", path)
            for name, child in schema["properties"].items():
                self._assert_structural(child, f"{path}.{name}")
        if "items" in schema:
            self.assertEqual(schema["type"], "array", path)
            self._assert_structural(schema["items"], f"{path}[]")

    def test_schema_uses_re2_compatible_patterns(self) -> None:
        text = _CRD_PATH.read_text(encoding="utf-8")
        self.assertNotIn("(?:", text)
        for pattern in self._patterns(self.schema):
            re.compile(pattern)

    def _patterns(self, schema: dict):
        if "pattern" in schema:
            yield schema["pattern"]
        for child in schema.get("properties", {}).values():
            yield from self._patterns(child)
        if "items" in schema:
            yield from self._patterns(schema["items"])

    def test_policy_defaults_are_fail_closed(self) -> None:
        policy = self.spec_schema["properties"]["policy"]
        self.assertEqual(policy["default"], {})
        expected = {
            "failureAction": ("Recover", codec._POLICY_FAILURE_ACTIONS),
            "unverifiableAction": (
                "Block",
                codec._POLICY_UNVERIFIABLE_ACTIONS,
            ),
            "terminalEvidence": (
                "Required",
                codec._POLICY_TERMINAL_EVIDENCE,
            ),
        }
        for field, (value, allowed) in expected.items():
            with self.subTest(field=field):
                field_schema = policy["properties"][field]
                self.assertEqual(field_schema["default"], value)
                self.assertEqual(set(field_schema["enum"]), set(allowed))

        authority = self.spec_schema["properties"]["authorities"]["items"]
        self.assertEqual(
            authority["properties"]["compatibility"]["default"],
            AuthoritySpec("authority", "release", "provider").compatibility,
        )
        references = [
            self.spec_schema["properties"]["workload"]["properties"]["ref"],
            authority["properties"]["parametersRef"],
            self.spec_schema["properties"]["stages"]["items"]["properties"][
                "parametersRef"
            ],
            self.status_schema["properties"]["terminalEvidenceRef"],
        ]
        for reference in references:
            self.assertEqual(
                reference["properties"]["apiGroup"]["default"],
                LocalObjectReference("ConfigMap", "parameters").api_group,
            )

    def test_stage_and_status_collections_have_kubernetes_semantics(self) -> None:
        spec_properties = self.spec_schema["properties"]
        self._assert_list_map(spec_properties["authorities"], "name")
        self._assert_list_map(spec_properties["recoverySets"], "name")
        self._assert_list_map(spec_properties["stages"], "id")

        stage = spec_properties["stages"]["items"]["properties"]
        self._assert_list_set(stage["requires"])
        self._assert_list_map(stage["inputBindings"], "name")
        self._assert_list_set(stage["publish"])
        self._assert_list_set(stage["recoverySets"])

        status = self.status_schema["properties"]
        self._assert_list_map(status["conditions"], "type")
        self._assert_list_map(status["recoverySets"], "name")

    def _assert_list_map(self, schema: dict, key: str) -> None:
        self.assertEqual(schema["x-kubernetes-list-type"], "map")
        self.assertEqual(schema["x-kubernetes-list-map-keys"], [key])
        self.assertGreater(schema["maxItems"], 0)

    def _assert_list_set(self, schema: dict) -> None:
        self.assertEqual(schema["x-kubernetes-list-type"], "set")
        self.assertGreater(schema["maxItems"], 0)

    def test_spec_is_immutable_and_rejects_self_dependency(self) -> None:
        rules = [item["rule"] for item in self.spec_schema["x-kubernetes-validations"]]
        self.assertIn("self == oldSelf", rules)
        messages = {
            item["message"] for item in self.spec_schema["x-kubernetes-validations"]
        }
        self.assertEqual(
            messages,
            {
                "spec is immutable",
                "a stage cannot depend on itself",
            },
        )

    def test_root_status_is_bound_to_recovery_declarations(self) -> None:
        messages = {item["message"] for item in self.schema["x-kubernetes-validations"]}
        self.assertEqual(
            messages,
            {
                "status recovery sets must match their declarations",
                "successful status requires every declared recovery set",
                "terminal status is immutable",
            },
        )

    def test_status_validates_terminal_evidence_and_generations(self) -> None:
        status_messages = {
            item["message"] for item in self.status_schema["x-kubernetes-validations"]
        }
        self.assertEqual(
            status_messages,
            {
                "terminal evidence must match the terminal phase",
                "terminal status requires a positive observed generation",
                "condition generations cannot exceed status generation",
            },
        )

    def test_codec_and_schema_limits_match(self) -> None:
        spec = self.spec_schema["properties"]
        workload = spec["workload"]["properties"]
        self.assertEqual(
            workload["name"]["maxLength"],
            codec._MAX_WORKLOAD_NAME_LENGTH,
        )
        self.assertEqual(
            workload["revision"]["maxLength"],
            codec._MAX_WORKLOAD_REVISION_LENGTH,
        )
        self.assertEqual(
            workload["digest"]["pattern"],
            contract_validation._SHA256_RE.pattern,
        )

        phases = self.status_schema["properties"]["phase"]["enum"]
        self.assertEqual(set(phases), set(codec._PHASES))
        condition = self.status_schema["properties"]["conditions"]["items"]
        self.assertEqual(
            set(condition["properties"]["status"]["enum"]),
            set(codec._CONDITION_STATUSES),
        )
        self.assertIn("message", condition["required"])

        stage = spec["stages"]["items"]["properties"]
        limits = {
            "authorities": (spec["authorities"], codec._MAX_AUTHORITIES),
            "recoverySets": (spec["recoverySets"], codec._MAX_RECOVERY_SETS),
            "stages": (spec["stages"], codec._MAX_STAGES),
            "requires": (stage["requires"], codec._MAX_STAGES),
            "inputBindings": (
                stage["inputBindings"],
                codec._MAX_INPUT_BINDINGS,
            ),
            "publish": (stage["publish"], codec._MAX_STAGE_ITEMS),
            "stageRecoverySets": (
                stage["recoverySets"],
                codec._MAX_RECOVERY_SETS,
            ),
            "conditions": (
                self.status_schema["properties"]["conditions"],
                codec._MAX_CONDITIONS,
            ),
            "statusRecoverySets": (
                self.status_schema["properties"]["recoverySets"],
                codec._MAX_RECOVERY_SETS,
            ),
        }
        for name, (schema, maximum) in limits.items():
            with self.subTest(name=name):
                self.assertEqual(schema["maxItems"], maximum)

    def test_token_and_reference_constraints_are_consistent(self) -> None:
        token_pattern = contract_validation._TOKEN_RE.pattern
        spec = self.spec_schema["properties"]
        stage = spec["stages"]["items"]["properties"]
        recovery_set = spec["recoverySets"]["items"]["properties"]
        input_binding = stage["inputBindings"]["items"]["properties"]
        status_recovery = self.status_schema["properties"]["recoverySets"]["items"][
            "properties"
        ]
        token_schemas = [
            spec["authorities"]["items"]["properties"][name]
            for name in ("name", "capability", "provider")
        ]
        token_schemas.append(recovery_set["name"])
        token_schemas.extend(
            recovery_set["producer"]["properties"][name]
            for name in ("stage", "evidence", "role")
        )
        token_schemas.extend(
            [
                stage["id"],
                stage["adapterRef"]["properties"]["name"],
                stage["operation"],
                stage["requires"]["items"],
                stage["publish"]["items"],
                stage["recoverySets"]["items"],
                stage["authorityRef"],
                stage["recoveryOperation"],
            ]
        )
        token_schemas.extend(
            input_binding[name] for name in ("name", "stage", "output")
        )
        token_schemas.extend(
            status_recovery[name] for name in ("name", "evidence", "role")
        )
        for schema in token_schemas:
            self.assertEqual(schema["maxLength"], 64)
            self.assertEqual(schema["pattern"], token_pattern)

        dns_pattern = (
            "^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?"
            "(\\.[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?)*$"
        )
        references = [
            spec["workload"]["properties"]["ref"],
            spec["authorities"]["items"]["properties"]["parametersRef"],
            stage["parametersRef"],
            self.status_schema["properties"]["terminalEvidenceRef"],
        ]
        for reference in references:
            properties = reference["properties"]
            self.assertEqual(
                properties["name"]["maxLength"],
                codec._MAX_DNS_SUBDOMAIN_LENGTH,
            )
            self.assertEqual(
                properties["name"]["pattern"], codec._DNS_SUBDOMAIN_RE.pattern
            )
            self.assertEqual(
                properties["apiGroup"]["maxLength"],
                codec._MAX_DNS_SUBDOMAIN_LENGTH,
            )
            self.assertEqual(properties["apiGroup"]["pattern"], f"^$|{dns_pattern}")
            self.assertEqual(
                properties["kind"]["pattern"],
                codec._KIND_RE.pattern,
            )
        self.assertIsNotNone(re.fullmatch(dns_pattern, "a" * 63))
        self.assertIsNone(re.fullmatch(dns_pattern, "a" * 64))
        self.assertIsNotNone(codec._DNS_SUBDOMAIN_RE.fullmatch("a" * 64))

        digest_schemas = [
            spec["workload"]["properties"]["digest"],
            status_recovery["digest"],
            self.status_schema["properties"]["terminalEvidenceRef"]["properties"][
                "digest"
            ],
        ]
        for schema in digest_schemas:
            self.assertEqual(
                schema["pattern"],
                contract_validation._SHA256_RE.pattern,
            )

        condition = self.status_schema["properties"]["conditions"]["items"][
            "properties"
        ]
        self.assertEqual(
            condition["type"]["pattern"],
            codec._CONDITION_TYPE_RE.pattern,
        )
        self.assertEqual(
            condition["type"]["maxLength"],
            codec._MAX_CONDITION_TYPE_LENGTH,
        )
        self.assertEqual(
            condition["reason"]["pattern"],
            codec._CONDITION_REASON_RE.pattern,
        )
        self.assertEqual(
            condition["reason"]["maxLength"],
            codec._MAX_CONDITION_REASON_LENGTH,
        )
        self.assertEqual(
            condition["message"]["maxLength"],
            codec._MAX_CONDITION_MESSAGE_LENGTH,
        )

    def test_workload_identity_is_single_line(self) -> None:
        workload = self.spec_schema["properties"]["workload"]["properties"]
        for field in ("name", "revision"):
            pattern = workload[field]["pattern"]
            self.assertIsNotNone(re.fullmatch(pattern, "release candidate"))
            self.assertIsNone(re.fullmatch(pattern, "line\nbreak"))

    def test_sample_contract_passes_the_versioned_codec(self) -> None:
        payload = yaml.safe_load(_SAMPLE_PATH.read_text(encoding="utf-8"))

        resource = decode(payload)
        encoded = encode(resource)

        self.assertEqual(resource.spec.recovery_sets[0].stage, "prepare")
        self.assertEqual(resource.spec.stages[1].requires, ("prepare",))
        self.assertEqual(
            resource.spec.stages[1].input_bindings[0].output,
            "prepared-output",
        )
        self.assertEqual(encoded["spec"]["policy"]["failureAction"], "Recover")


if __name__ == "__main__":
    unittest.main()
