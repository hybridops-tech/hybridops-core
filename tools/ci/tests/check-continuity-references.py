"""Reference binding against the disposable API server in check-continuity-api.sh."""

import base64
import json
import unittest
from dataclasses import asdict
from unittest.mock import Mock

from continuity_cluster import client, kubectl
from hyops.controller.binding import BindingReceipt, bind_operation, verify_operation
from hyops.controller.references import ReferenceBindingError


STORE = "reference-records"
OPERATION = "reference-operation"


def create(namespace, kind, name, **fields):
    obj = {"apiVersion": "v1", "kind": kind, "metadata": {"name": name}, **fields}
    return json.loads(kubectl(namespace, "create", "-f", "-", "-o", "json", obj=obj))


class ReferenceBinding(unittest.TestCase):
    def test_persistent_binding(self):
        binder = client()
        name, data = "prepare-parameters", {"mode": "prepare"}
        initial = create("default", "ConfigMap", name, data=data)
        create(
            "default", "ConfigMap", "conformance-workload", data={"topology": "pair"}
        )
        marker = "synthetic-reference-secret"
        annotation = "synthetic-private-annotation"
        create("default", "Secret", "release-authority", stringData={"key": marker})
        secret = json.loads(
            kubectl(
                "default",
                "annotate",
                "secret/release-authority",
                f"fixture={annotation}",
                "-o",
                "json",
            )
        )

        receipt = bind_operation(binder, STORE, "default", OPERATION)
        key = f"configmap/{receipt.record_name}"
        stored = json.loads(kubectl(STORE, "get", key, "-o", "json"))
        self.assertTrue(stored["immutable"])
        self.assertEqual(set(stored["data"]), {"binding.json"})
        record = json.loads(stored["data"]["binding.json"])
        self.assertEqual(
            {(ref["kind"], ref["name"]) for ref in record["references"]},
            {
                ("Secret", "release-authority"),
                ("ConfigMap", name),
                ("ConfigMap", "conformance-workload"),
            },
        )
        identity = next(ref for ref in record["references"] if ref["kind"] == "Secret")
        self.assertEqual(
            identity,
            {
                "apiVersion": "v1",
                "kind": "Secret",
                **{
                    key: secret["metadata"][key]
                    for key in ("namespace", "name", "uid", "resourceVersion")
                },
            },
        )
        self.assertFalse(
            any(
                value in json.dumps(stored)
                for value in (
                    marker,
                    base64.b64encode(marker.encode()).decode(),
                    annotation,
                )
            ),
            "binding leaked Secret material",
        )

        restarted = client()
        retained = BindingReceipt(**json.loads(json.dumps(asdict(receipt))))
        self.assertEqual(
            bind_operation(restarted, STORE, "default", OPERATION), retained
        )
        downstream = Mock()

        def guarded():
            verify_operation(restarted, STORE, retained)
            downstream()

        guarded()
        downstream.assert_called_once_with()
        downstream.reset_mock()

        def expect_blocked(reason):
            with self.assertRaises(ReferenceBindingError) as failure:
                guarded()
            self.assertEqual(failure.exception.reason, reason)
            downstream.assert_not_called()

        kubectl("default", "delete", f"configmap/{name}")
        recreated = create("default", "ConfigMap", name, data=data)
        self.assertNotEqual(recreated["metadata"]["uid"], initial["metadata"]["uid"])
        expect_blocked("ReferenceChanged")
        with self.assertRaisesRegex(ReferenceBindingError, "^ReferenceChanged$"):
            bind_operation(restarted, STORE, "default", OPERATION)

        kubectl(STORE, "delete", key)
        expect_blocked("BindingMissing")
        self.assertEqual(
            kubectl(STORE, "get", key, "--ignore-not-found", "-o", "name"), ""
        )
        replacement = create(
            STORE, "ConfigMap", receipt.record_name, immutable=True, data=stored["data"]
        )
        self.assertNotEqual(replacement["metadata"]["uid"], stored["metadata"]["uid"])
        expect_blocked("BindingReplaced")


if __name__ == "__main__":
    unittest.main()
