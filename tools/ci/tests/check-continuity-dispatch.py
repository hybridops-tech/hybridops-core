"""Dispatch a persisted contract against a disposable local workload."""

import hashlib
import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from continuity_cluster import client, kubectl
from hyops.continuity.storage import FileOperationStore
from hyops.controller.binding import bind_operation
from hyops.controller.client import DISPATCH_ANNOTATION
from hyops.controller.execution import run_bound_operation
from hyops.controller.references import ReferenceBindingError
from tools.acceptance.continuity_contract.runner import (
    retirement_engine,
    retirement_resource,
)


STORE = "dispatch-records"


def stop_after_capture(root, receipt):
    adapter, engine = retirement_engine(
        root, receipt.operation_id, FileOperationStore(root / "operations")
    )
    execute = adapter.execute

    def capture_and_exit(request):
        result = execute(request)
        if request.operation == "capture":
            os._exit(91)
        return result

    with patch.object(adapter, "execute", capture_and_exit):
        run_bound_operation(client(), STORE, receipt, engine)


class BoundDispatch(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.original = os.urandom(64)
        self.digest = "sha256:" + hashlib.sha256(self.original).hexdigest()
        self.store = FileOperationStore(self.root / "operations")

    def prepare(self, name, *, fault=""):
        self.resource = retirement_resource(name)
        kubectl("default", "create", "--validate=strict", "-f", "-", obj=self.resource)
        self.receipt = bind_operation(client(), STORE, "default", name)
        self.adapter, self.engine = retirement_engine(
            self.root, self.receipt.operation_id, self.store, fault=fault
        )
        self.adapter.source.parent.mkdir()
        self.adapter.source.write_bytes(self.original)

    def run_persisted(self):
        result = run_bound_operation(client(), STORE, self.receipt, self.engine)
        self.assertEqual(result.operation_id, self.receipt.operation_id)
        self.assertEqual(
            result.workload.to_evidence(), self.resource["spec"]["workload"]
        )
        payload = json.loads(self.store.terminal_path(result.operation_id).read_text())
        self.assertEqual(payload, result.to_evidence())
        self.assertEqual(result.stages[0].evidence[0].digest, self.digest)
        return result

    def assert_redelivery_blocked(self):
        other_store = self.root / "other-operations"
        other_adapter, other_engine = retirement_engine(
            self.root, self.receipt.operation_id, FileOperationStore(other_store)
        )
        with self.assertRaisesRegex(ReferenceBindingError, "^DispatchAlreadyClaimed$"):
            run_bound_operation(client(), STORE, self.receipt, other_engine)
        self.assertEqual(other_adapter.calls, [])
        self.assertFalse(other_store.exists())

    def test_retirement_and_duplicate_delivery(self):
        self.prepare("dispatch-complete")
        result = self.run_persisted()
        self.assertEqual(result.status, "succeeded")
        self.assertFalse(self.adapter.source.parent.exists())
        self.assertEqual(self.adapter.retained.read_bytes(), self.original)
        self.assertEqual(self.adapter.replacement.read_bytes(), self.original)
        claim = json.loads(
            kubectl(
                STORE, "get", f"configmap/{self.receipt.operation_id}", "-o", "json"
            )
        )
        self.assertTrue(claim["immutable"])
        key = f"configmap/{self.receipt.record_name}"
        before = json.loads(kubectl(STORE, "get", key, "-o", "json"))
        self.assertEqual(
            before["metadata"]["annotations"][DISPATCH_ANNOTATION],
            self.receipt.operation_id,
        )
        updated = json.loads(
            kubectl(STORE, "annotate", key, f"{DISPATCH_ANNOTATION}-", "-o", "json")
        )
        self.assertNotIn(
            DISPATCH_ANNOTATION, updated["metadata"].get("annotations", {})
        )
        self.assert_redelivery_blocked()

    def test_competing_workers_dispatch_once(self):
        self.prepare("dispatch-competing")
        gate = threading.Barrier(2, timeout=10)
        other_adapter, other_engine = retirement_engine(
            self.root,
            self.receipt.operation_id,
            FileOperationStore(self.root / "other-operations"),
        )

        def deliver(engine):
            worker = client()
            create = worker.create_binding

            def competing_create(namespace, name, record):
                self.assertEqual(name, self.receipt.operation_id)
                gate.wait()
                return create(namespace, name, record)

            with patch.object(worker, "create_binding", competing_create):
                try:
                    return run_bound_operation(
                        worker, STORE, self.receipt, engine
                    ).status
                except ReferenceBindingError as failure:
                    return failure.reason

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(deliver, (self.engine, other_engine)))
        self.assertCountEqual(outcomes, ["succeeded", "DispatchAlreadyClaimed"])
        for adapter, outcome in zip((self.adapter, other_adapter), outcomes):
            if outcome == "succeeded":
                self.assertEqual(adapter.calls.count(("execute", "retire")), 1)
            else:
                self.assertEqual(adapter.calls, [])
        self.assertEqual(self.adapter.replacement.read_bytes(), self.original)

    def test_restart_after_capture_does_not_repeat_effects(self):
        self.prepare("dispatch-interrupted")
        process = multiprocessing.get_context("spawn").Process(
            target=stop_after_capture, args=(self.root, self.receipt)
        )
        process.start()
        try:
            process.join(45)
            self.assertEqual(process.exitcode, 91)
        finally:
            if process.is_alive():
                process.kill()
                process.join(5)
            process.close()
        self.assertEqual(self.adapter.retained.read_bytes(), self.original)
        self.assertEqual(self.adapter.source.read_bytes(), self.original)
        self.assertFalse(self.store.terminal_path(self.receipt.operation_id).exists())
        self.assert_redelivery_blocked()

    def test_status_cannot_authorise_retirement_after_evidence_changes(self):
        self.prepare("dispatch-corrupt", fault="changed")
        status = {
            "observedGeneration": 1,
            "phase": "Pending",
            "recoverySets": [
                {
                    "name": "saved",
                    "evidence": "state",
                    "role": "recovery",
                    "digest": self.digest,
                }
            ],
        }
        kubectl(
            "default",
            "patch",
            "continuitycontract/dispatch-corrupt",
            "--subresource=status",
            "--type=merge",
            "--patch",
            json.dumps({"status": status}),
        )
        result = self.run_persisted()
        self.assertEqual(
            (result.status, result.reason_code),
            ("failed", "retained_evidence_mismatch"),
        )
        self.assertEqual(self.adapter.source.read_bytes(), self.original)
        self.assertNotEqual(self.adapter.retained.read_bytes(), self.original)
        self.assertNotIn(("execute", "retire"), self.adapter.calls)
        self.assertFalse(self.adapter.replacement.parent.exists())

    def replace_binding(self):
        key = f"configmap/{self.receipt.record_name}"
        original = json.loads(kubectl(STORE, "get", key, "-o", "json"))
        self.assertTrue(original["immutable"])
        replacement = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": self.receipt.record_name},
            "immutable": True,
            "data": original["data"],
        }
        kubectl(STORE, "delete", key)
        created = json.loads(
            kubectl(STORE, "create", "-f", "-", "-o", "json", obj=replacement)
        )
        self.assertNotEqual(created["metadata"]["uid"], self.receipt.record_uid)

    def test_binding_replaced_after_capture_prevents_retirement(self):
        self.prepare("dispatch-replaced")
        admit = self.adapter.admit

        def replace_on_retire(request):
            decision = admit(request)
            if request.operation == "retire":
                self.replace_binding()
            return decision

        with patch.object(self.adapter, "admit", replace_on_retire):
            result = self.run_persisted()
        self.assertEqual(
            (result.status, result.reason_code),
            ("failed", "operation_binding_unverified"),
        )
        self.assertNotIn(("execute", "retire"), self.adapter.calls)
        self.assertEqual(self.adapter.retained.read_bytes(), self.original)
        self.assertEqual(self.adapter.source.read_bytes(), self.original)
        self.assertFalse(self.adapter.replacement.parent.exists())


if __name__ == "__main__":
    unittest.main()
