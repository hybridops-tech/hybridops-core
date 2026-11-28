import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import yaml

from hyops.continuity.json_values import digest_json
from hyops.controller.references import (
    ReferenceBindingError,
    resolve_references,
    verify_references,
)


SAMPLE = (
    Path(__file__).resolve().parents[3]
    / "config/samples/continuity_v1alpha1_contract.yaml"
)


class ReferenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.contract = yaml.safe_load(SAMPLE.read_text(encoding="utf8"))
        self.name = self.contract["metadata"]["name"]
        self.contract["metadata"].update(
            namespace="lab", uid="contract", generation=1, resourceVersion="1"
        )
        self.refs = {}
        for kind, name in (
            ("ConfigMap", self.name),
            ("ConfigMap", "prepare-parameters"),
            ("Secret", "release-authority"),
        ):
            obj = {
                "metadata": {
                    "namespace": "lab",
                    "name": name,
                    "uid": name,
                    "resourceVersion": "2",
                }
            }
            if kind == "ConfigMap":
                obj.update(
                    apiVersion="v1",
                    kind=kind,
                    data={"a": "sample"},
                    binaryData={"b": "Yg=="},
                )
            else:
                obj.update(apiVersion="meta.k8s.io/v1", kind="PartialObjectMetadata")
                obj["metadata"]["annotations"] = {"example": "unsafe-secret-annotation"}
            self.refs[kind, name] = obj
        self.client = Mock(spec_set=["read", "read_reference"])
        self.client.read.side_effect = lambda *_: deepcopy(self.contract)
        self.client.read_reference.side_effect = self._read_ref

    def _read_ref(self, namespace, kind, name):
        self.assertEqual(namespace, "lab")
        return deepcopy(self.refs.get((kind, name)))

    def resolve(self):
        return resolve_references(self.client, "lab", self.name)

    def verify(self, record):
        verify_references(self.client, "lab", self.name, record)

    def test_record_binds_shared_objects_once_without_persisting_private_values(self):
        self.contract["spec"]["stages"][1]["parametersRef"] = {
            "name": self.name,
            "kind": "ConfigMap",
        }
        record = self.resolve()
        self.assertEqual(self.client.read_reference.call_count, 3)
        self.assertEqual(
            record["contract"]["specDigest"], digest_json(self.contract["spec"])
        )
        for ref in record["references"]:
            if ref["kind"] == "ConfigMap":
                self.assertEqual(
                    ref["contentDigest"],
                    digest_json({"data": {"a": "sample"}, "binaryData": {"b": "Yg=="}}),
                )
            else:
                self.assertEqual(
                    set(ref),
                    {
                        "apiVersion",
                        "kind",
                        "namespace",
                        "name",
                        "uid",
                        "resourceVersion",
                    },
                )
        encoded = json.dumps(record)
        for sensitive in ("unsafe-secret-annotation", '"sample"', "Yg=="):
            self.assertNotIn(sensitive, encoded)
        self.contract["metadata"]["resourceVersion"] = "99"
        self.verify(json.loads(encoded))

    def test_replaced_revised_missing_and_changed_content_fail_verification(self):
        record = self.resolve()
        key = ("ConfigMap", self.name)
        original = self.refs[key]
        for change in (
            "uid",
            "resourceVersion",
            "data",
            "binaryData",
            "deleted",
            "deleting",
        ):
            with self.subTest(change=change):
                obj = deepcopy(original)
                self.refs[key] = obj
                if change == "deleted":
                    del self.refs[key]
                elif change == "deleting":
                    obj["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
                elif change in ("uid", "resourceVersion"):
                    obj["metadata"][change] = "replacement"
                else:
                    obj[change] = {}
                with self.assertRaises(ReferenceBindingError):
                    self.verify(record)

    def test_secret_revision_and_full_secret_response_cannot_verify(self):
        record = self.resolve()
        secret = self.refs["Secret", "release-authority"]
        secret["metadata"]["resourceVersion"] = "3"
        with self.assertRaisesRegex(ReferenceBindingError, "^ReferenceChanged$"):
            self.verify(record)
        secret["data"] = {"password": "private"}
        with self.assertRaisesRegex(ReferenceBindingError, "^InvalidSecretMetadata$"):
            self.resolve()
        secret.update(kind="Secret", apiVersion="v1")
        with self.assertRaisesRegex(ReferenceBindingError, "^InvalidReference$"):
            self.resolve()

    def test_does_not_read_referents_of_replaced_or_changed_contract(self):
        record = self.resolve()
        pristine = deepcopy(self.contract)
        for change in ("uid", "generation", "spec", "deleting", "phase", "invalid"):
            with self.subTest(change=change):
                self.contract = deepcopy(pristine)
                if change == "spec":
                    self.contract["spec"]["workload"]["revision"] = "v2"
                elif change == "phase":
                    self.contract["status"] = {"phase": "Running"}
                elif change == "invalid":
                    self.contract["spec"]["unknown"] = "private"
                elif change == "deleting":
                    self.contract["metadata"]["deletionTimestamp"] = (
                        "2026-01-01T00:00:00Z"
                    )
                else:
                    self.contract["metadata"][change] = (
                        2 if change == "generation" else "another"
                    )
                self.client.read_reference.reset_mock()
                with self.assertRaises(ReferenceBindingError):
                    self.verify(record)
                self.client.read_reference.assert_not_called()

    def test_second_contract_read_detects_replacement(self):
        replacement = deepcopy(self.contract)
        replacement["metadata"]["uid"] = "new"
        self.client.read.side_effect = [self.contract, replacement]
        with self.assertRaisesRegex(ReferenceBindingError, "^ContractChanged$"):
            self.resolve()

    def test_rejects_unknown_references_before_any_lookup(self):
        ref = self.contract["spec"]["stages"][0]["parametersRef"]
        for kind, group in (("Node", ""), ("ConfigMap", "other.example")):
            ref.update(kind=kind, apiGroup=group)
            with self.assertRaisesRegex(
                ReferenceBindingError, "^UnsupportedReference$"
            ):
                self.resolve()
        self.client.read_reference.assert_not_called()

    def test_modified_record_must_not_authorize_an_incomplete_reference_set(self):
        record = self.resolve()
        for mutate in (
            lambda r: r.pop("contract"),
            lambda r: r.update(kind="ConfigMap"),
            lambda r: r["contract"].update(resourceVersion=""),
            lambda r: r["contract"].update(generation=True),
            lambda r: r["references"].pop(),
            lambda r: r["references"][0].update(uid="wrong"),
        ):
            clone = deepcopy(record)
            mutate(clone)
            with self.assertRaises(ReferenceBindingError):
                self.verify(clone)

    def test_refused_wrong_namespace_or_malformed_binary_data(self):
        obj = self.refs["ConfigMap", self.name]
        obj["metadata"]["namespace"] = "other"
        with self.assertRaisesRegex(ReferenceBindingError, "^InvalidObjectIdentity$"):
            self.resolve()
        obj["metadata"]["namespace"] = "lab"
        obj["binaryData"]["b"] = "invalid-value"
        with self.assertRaisesRegex(ReferenceBindingError, "^InvalidConfigMap$"):
            self.resolve()
