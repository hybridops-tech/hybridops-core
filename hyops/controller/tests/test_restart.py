import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from hyops.controller.binding import claim_dispatch
from hyops.controller.client import DISPATCH_ANNOTATION, TERMINAL_ANNOTATION
from hyops.controller.reconcile import reconcile
from hyops.controller.references import ReferenceBindingError
from hyops.controller.tests.test_terminal import TerminalFixture


class RestartReconciliationTests(TerminalFixture, unittest.TestCase):
    def worker(self):
        worker = Mock(
            spec_set=[
                "read",
                "read_binding",
                "read_terminal_evidence",
                "replace_status",
                "replace_terminal_status",
            ]
        )
        worker.read.side_effect = lambda *_: deepcopy(self.obj)
        worker.read_binding.side_effect = self.read_record
        worker.read_terminal_evidence.side_effect = self.read_record

        def write(ns, name, uid, version, status, **_):
            meta = self.obj["metadata"]
            self.assertEqual(
                (ns, name, uid, version),
                (
                    meta["namespace"],
                    meta["name"],
                    meta["uid"],
                    meta["resourceVersion"],
                ),
            )
            self.obj["status"] = deepcopy(status)
            meta["resourceVersion"] = str(int(version) + 1)

        worker.replace_status.side_effect = write
        worker.replace_terminal_status.side_effect = write
        return worker

    def restart(self, worker):
        return reconcile(worker, "lab", "run", record_namespace="records")

    def assert_unresolved(self):
        worker = self.worker()
        before = deepcopy(self.obj)
        with self.assertRaises(ReferenceBindingError):
            self.restart(worker)
        self.assertEqual(self.obj, before)
        worker.replace_status.assert_not_called()
        worker.replace_terminal_status.assert_not_called()

    def test_dispatched_result_survives_worker_replacement(self):
        self.retain()
        original = deepcopy(self.objects)
        first = self.worker()
        self.assertTrue(self.restart(first))
        self.assertEqual(self.obj["status"]["phase"], "Failed")
        first.replace_terminal_status.assert_called_once()
        second = self.worker()
        self.assertFalse(self.restart(second))
        second.replace_terminal_status.assert_not_called()
        self.assertEqual(self.objects, original)
        self.engine.run.assert_called_once()

    def test_missing_or_replaced_records_are_not_rebuilt(self):
        self.retain()
        for ns, key in (
            ("records", self.receipt.record_name),
            ("records", self.receipt.operation_id),
            ("records", self.key),
            ("lab", self.key),
        ):
            with self.subTest(key=key, ns=ns), patch.dict(self.objects):
                original = self.objects.pop((ns, key))
                self.assert_unresolved()
                self.objects[ns, key] = {
                    **original,
                    "metadata": {**original["metadata"], "uid": "replacement"},
                }
                self.assert_unresolved()
        self.engine.run.assert_called_once()

    def test_partial_dispatch_or_witness_pin_is_not_completed(self):
        self.retain()
        meta = self.objects["records", self.receipt.record_name]["metadata"]
        for key in (DISPATCH_ANNOTATION, TERMINAL_ANNOTATION):
            with self.subTest(key=key), patch.dict(meta["annotations"]):
                del meta["annotations"][key]
                self.assert_unresolved()

    def test_claim_without_a_kernel_result_is_not_replayed(self):
        claim_dispatch(self.client, "records", self.receipt)
        original = deepcopy(self.objects)
        self.assert_unresolved()
        self.assertEqual(self.objects, original)
        self.engine.run.assert_not_called()

    def test_terminal_status_is_not_a_replacement_for_missing_records(self):
        self.retain()
        self.assertTrue(self.restart(self.worker()))
        self.objects.clear()
        self.assert_unresolved()

    def test_claim_cannot_supply_a_new_binding(self):
        self.retain()
        data = self.objects["records", self.receipt.operation_id]["data"]
        claim = json.loads(data["binding.json"])
        for field, val in (
            ("contractUid", "other"),
            ("bindingUid", "other"),
            ("bindingDigest", "sha256:" + "c" * 64),
            ("operationId", "other"),
        ):
            with (
                self.subTest(field=field),
                patch.dict(data, {"binding.json": json.dumps({**claim, field: val})}),
            ):
                self.assert_unresolved()

    def test_new_contract_with_reused_name_does_not_inherit_result(self):
        self.retain()
        self.obj["metadata"].update(uid="new-uid", generation=1, resourceVersion="1")
        worker = self.worker()
        self.assertTrue(self.restart(worker))
        self.assertEqual(self.obj["status"]["phase"], "Pending")
        self.assertNotIn("terminalEvidenceRef", self.obj["status"])
        worker.replace_terminal_status.assert_not_called()

    def test_undispatched_contract_keeps_validation_only(self):
        for bound in (False, True):
            with (
                self.subTest(bound=bound),
                patch.dict(self.objects, clear=not bound),
                patch.dict(self.obj),
            ):
                self.assertTrue(self.restart(self.worker()))
                self.assertEqual(
                    self.obj["status"]["conditions"][0]["type"], "ContractValid"
                )
                self.assertEqual(self.obj["status"]["phase"], "Pending")
                self.assertFalse(self.restart(self.worker()))
        self.engine.run.assert_not_called()
