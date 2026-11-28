"""Status-only acceptance against the two persisted fixtures in check-continuity-api.sh."""

import json
import subprocess
import unittest
from unittest.mock import patch

from continuity_cluster import client as cluster_client
from hyops.controller.reconcile import StatusConflict, reconcile


class StatusReconciliation(unittest.TestCase):
    def test_status_projection(self):
        for name, valid, reason in (
            ("default-policy", "True", "Validated"),
            ("unknown-field", "False", "UnknownField"),
        ):
            with self.subTest(name=name):
                self.check_projection(name, valid, reason)

    def check_projection(self, name, valid, reason):
        client = cluster_client()
        read = client.read
        snapshots = []
        observer = {
            "type": "InventoryReady",
            "status": "True",
            "observedGeneration": 1,
            "lastTransitionTime": "2026-01-01T00:00:00Z",
            "reason": "Observed",
            "message": "Recorded.",
        }

        def read_then_publish(namespace, key):
            obj = read(namespace, key)
            snapshots.append(obj)
            if len(snapshots) == 1:
                update = {
                    "metadata": {"resourceVersion": obj["metadata"]["resourceVersion"]},
                    "status": {"observedGeneration": 1, "conditions": [observer]},
                }
                subprocess.run(
                    [
                        "kubectl",
                        "patch",
                        f"continuitycontract/{key}",
                        f"--namespace={namespace}",
                        "--request-timeout=10s",
                        "--subresource=status",
                        "--type=merge",
                        "--patch=" + json.dumps(update),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    timeout=15,
                )
            return obj

        with patch.object(client, "read", side_effect=read_then_publish):
            self.assertTrue(reconcile(client, "default", name))
        before, competing = snapshots
        metadata = before["metadata"]
        self.assertEqual(competing["spec"], before["spec"])
        self.assertEqual(competing["metadata"]["uid"], metadata["uid"])
        self.assertNotEqual(
            competing["metadata"]["resourceVersion"], metadata["resourceVersion"]
        )
        self.assertEqual(competing["status"]["conditions"], [observer])
        published = client.read("default", name)
        self.assertEqual(published["spec"], before["spec"])
        self.assertEqual(published["metadata"]["uid"], metadata["uid"])
        self.assertEqual(published["metadata"]["generation"], metadata["generation"])
        self.assertNotEqual(
            published["metadata"]["resourceVersion"], metadata["resourceVersion"]
        )
        status = published["status"]
        self.assertEqual(status["phase"], "Pending")
        self.assertEqual(status["observedGeneration"], metadata["generation"])
        archived = before.get("status", {}).get("recoverySets", [])
        self.assertEqual(len(archived), 1 if valid == "False" else 0)
        self.assertEqual(status["recoverySets"], archived)
        self.assertNotIn("terminalEvidenceRef", status)
        conditions = {item["type"]: item for item in status["conditions"]}
        self.assertEqual(conditions.keys(), {"InventoryReady", "ContractValid"})
        self.assertEqual(conditions["InventoryReady"], observer)
        condition = conditions["ContractValid"]
        self.assertEqual(condition["status"], valid)
        self.assertEqual(condition["reason"], reason)
        self.assertEqual(condition["observedGeneration"], metadata["generation"])

        for redelivery in (client, cluster_client()):
            self.assertIs(reconcile(redelivery, "default", name), False)
            self.assertEqual(redelivery.read("default", name), published)

        desired = {
            **status,
            "conditions": [observer, {**condition, "message": "Rechecked."}],
        }
        self.check_write_preconditions(client, name, metadata, published, desired)

    def check_write_preconditions(self, client, name, metadata, published, desired):
        current_version = published["metadata"]["resourceVersion"]
        with self.assertRaises(StatusConflict):
            client.replace_status(
                "default", name, metadata["uid"], metadata["resourceVersion"], desired
            )
        other = "unknown-field" if name == "default-policy" else "default-policy"
        other_uid = client.read("default", other)["metadata"]["uid"]
        self.assertNotEqual(other_uid, metadata["uid"])
        try:
            client.replace_status("default", name, other_uid, current_version, desired)
        except StatusConflict:
            pass
        except RuntimeError as exc:
            self.assertRegex(str(exc), r"HTTP 422$")
        else:
            self.fail("status update with the wrong UID was accepted")
        self.assertEqual(client.read("default", name), published)
        # Only the UID differs from the rejected request.
        client.replace_status(
            "default", name, metadata["uid"], current_version, desired
        )
        self.assertIn(
            desired["conditions"][1],
            client.read("default", name)["status"]["conditions"],
        )


if __name__ == "__main__":
    unittest.main()
