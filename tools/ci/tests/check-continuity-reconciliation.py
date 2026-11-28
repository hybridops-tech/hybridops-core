"""Status-only acceptance against the two persisted fixtures in check-continuity-api.sh."""

import os
import unittest
from http.client import HTTPConnection

from hyops.controller.client import ContractClient
from hyops.controller.reconcile import StatusConflict, reconcile


class StatusReconciliation(unittest.TestCase):
    def client(self):
        port = int(os.environ["HYOPS_TEST_PROXY_PORT"])
        return ContractClient(lambda: HTTPConnection("127.0.0.1", port, timeout=10))

    def test_status_projection(self):
        for name, valid, reason in (
            ("default-policy", "True", "Validated"),
            ("unknown-field", "False", "UnknownField"),
        ):
            with self.subTest(name=name):
                self.check_projection(name, valid, reason)

    def check_projection(self, name, valid, reason):
        client = self.client()
        before = client.read("default", name)
        self.assertIsNotNone(before)
        self.assertNotIn("status", before)
        metadata = before["metadata"]
        self.assertIs(reconcile(client, "default", name), True)
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
        self.assertEqual(status["recoverySets"], [])
        self.assertNotIn("terminalEvidenceRef", status)
        [condition] = status["conditions"]
        self.assertEqual(condition["type"], "ContractValid")
        self.assertEqual(condition["status"], valid)
        self.assertEqual(condition["reason"], reason)
        self.assertEqual(condition["observedGeneration"], metadata["generation"])

        # An earlier read cannot remove the condition written by a newer delivery.
        with self.assertRaises(StatusConflict):
            client.replace_status(
                "default",
                name,
                metadata["uid"],
                metadata["resourceVersion"],
                {**status, "conditions": []},
            )
        self.assertEqual(client.read("default", name), published)
        for redelivery in (client, self.client()):
            self.assertIs(reconcile(redelivery, "default", name), False)
            self.assertEqual(redelivery.read("default", name), published)


if __name__ == "__main__":
    unittest.main()
