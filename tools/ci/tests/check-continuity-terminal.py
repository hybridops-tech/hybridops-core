"""Publish verified terminal evidence against a disposable API server."""

import hashlib
import json
import multiprocessing
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from continuity_cluster import client, kubectl
from hyops.continuity.engine import ContinuityEngine
from hyops.continuity.storage import FileOperationStore
from hyops.controller.binding import bind_operation
from hyops.controller.reconcile import reconcile
from hyops.controller.references import ReferenceBindingError
from hyops.controller.terminal import publish_terminal_status, run_and_retain_terminal
from tools.acceptance.continuity_contract.runner import (
    _engine,
    _LocalAdapter,
    retirement_engine,
    retirement_resource,
)


LABS, RECORDS = "terminal-labs", "terminal-records"


def digest(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()


def fresh_worker(function, *args):
    with multiprocessing.get_context("spawn").Pool(1) as worker:
        return worker.apply_async(function, args).get(timeout=45)


def dispatch_before_restart(name, stop_before_pin):
    worker = client()
    receipt = bind_operation(worker, RECORDS, LABS, name)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        adapter, engine = retirement_engine(
            root, receipt.operation_id, FileOperationStore(root / "operations")
        )
        adapter.source.parent.mkdir()
        adapter.source.write_bytes(b"restart test")
        if stop_before_pin:
            publication = patch.object(
                worker, "pin_terminal_witness", side_effect=InterruptedError
            )
        else:
            publication = nullcontext()
        with publication:
            try:
                run_and_retain_terminal(worker, RECORDS, receipt, engine)
            except InterruptedError:
                if not stop_before_pin:
                    raise
        return [stage for action, stage in adapter.calls if action == "execute"]


def reconcile_after_restart(namespace, name, records):
    worker = client()
    send = worker._request

    def status_writes_only(method, ns, key, *args, **kwargs):
        if method != "GET" and (
            (method, ns, key) != ("PUT", namespace, name)
            or kwargs.get("resource", "continuitycontracts") != "continuitycontracts"
        ):
            raise AssertionError(f"unexpected restart write: {method} {ns}/{key}")
        return send(method, ns, key, *args, **kwargs)

    with (
        patch.object(worker, "_request", status_writes_only),
        patch.object(ContinuityEngine, "run", side_effect=AssertionError("redispatch")),
    ):
        return reconcile(worker, namespace, name, record_namespace=records)


class TerminalPublication(unittest.TestCase):
    def bind(self, resource):
        kubectl(LABS, "create", "--validate=strict", "-f", "-", obj=resource)
        self.receipt = bind_operation(
            client(), RECORDS, LABS, resource["metadata"]["name"]
        )
        self.evidence = "terminal-" + self.receipt.operation_id.removeprefix(
            "dispatch-"
        )

    def execute(self, name, *, fault=""):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bind(retirement_resource(name))
        store = FileOperationStore(root / "operations")
        self.adapter, engine = retirement_engine(
            root, self.receipt.operation_id, store, fault=fault
        )
        self.adapter.source.parent.mkdir()
        original = b"terminal publication test"
        self.adapter.source.write_bytes(original)
        self.recovery = {
            "name": "saved",
            "evidence": "state",
            "role": "recovery",
            "digest": digest(original),
        }
        self.result = run_and_retain_terminal(client(), RECORDS, self.receipt, engine)
        local = store.terminal_path(self.receipt.operation_id).read_bytes()
        public = client().read_terminal_evidence(LABS, self.evidence)
        self.assertEqual(public["data"]["terminal.json"].encode(), local)
        self.assertEqual(json.loads(local), self.result.to_evidence())
        self.calls = list(self.adapter.calls)
        self.assertEqual(self.status().get("phase", "Pending"), "Pending")

    def status(self):
        return client().read(LABS, self.receipt.name).get("status", {})

    def patch_status(self, fields):
        kubectl(
            LABS,
            "patch",
            f"continuitycontract/{self.receipt.name}",
            "--subresource=status",
            "--type=merge",
            "--patch",
            json.dumps({"status": fields}),
        )

    def publish(self, worker=None):
        return publish_terminal_status(worker or client(), RECORDS, self.receipt)

    def assert_refused(self, worker=None):
        before = self.status()
        with self.assertRaises(ReferenceBindingError):
            self.publish(worker)
        self.assertEqual(self.status(), before)
        self.assertEqual(self.adapter.calls, self.calls)

    def test_worker_restart_publishes_from_cluster_records_only(self):
        name = "terminal-restart"
        kubectl(LABS, "create", "-f", "-", obj=retirement_resource(name))
        self.assertEqual(
            fresh_worker(dispatch_before_restart, name, False),
            ["capture", "retire", "restore"],
        )
        before = client().read(LABS, name)
        self.assertEqual(before.get("status", {}).get("phase", "Pending"), "Pending")
        self.assertTrue(fresh_worker(reconcile_after_restart, LABS, name, RECORDS))
        published = client().read(LABS, name)
        self.assertEqual(published["status"]["phase"], "Succeeded")
        self.assertEqual(
            published["status"]["recoverySets"][0]["digest"], digest(b"restart test")
        )
        self.assertFalse(fresh_worker(reconcile_after_restart, LABS, name, RECORDS))
        self.assertEqual(client().read(LABS, name), published)

    def test_worker_restart_refuses_unpinned_witness(self):
        name = "terminal-unpinned"
        kubectl(LABS, "create", "-f", "-", obj=retirement_resource(name))
        self.assertEqual(
            fresh_worker(dispatch_before_restart, name, True),
            ["capture", "retire", "restore"],
        )
        before = client().read(LABS, name)
        self.assertEqual(before.get("status", {}).get("phase", "Pending"), "Pending")
        with self.assertRaisesRegex(ReferenceBindingError, "^TerminalWitnessChanged$"):
            fresh_worker(reconcile_after_restart, LABS, name, RECORDS)
        self.assertEqual(client().read(LABS, name), before)

    def test_status_conflict_rechecks_evidence_without_dispatch(self):
        self.execute("terminal-complete")
        observer = {
            "type": "InventoryReady",
            "status": "True",
            "observedGeneration": 1,
            "lastTransitionTime": "2026-01-01T00:00:00Z",
            "reason": "Observed",
            "message": "Inventory checked.",
        }
        worker = client()
        put = worker.replace_terminal_status
        versions = []

        def competing_put(namespace, name, uid, version, status, **kwargs):
            versions.append(version)
            if len(versions) == 1:
                self.patch_status({"observedGeneration": 1, "conditions": [observer]})
            return put(namespace, name, uid, version, status, **kwargs)

        with patch.object(worker, "replace_terminal_status", competing_put):
            self.assertTrue(self.publish(worker))
        self.assertEqual(len(set(versions)), 2)
        public = worker.read_terminal_evidence(LABS, self.evidence)
        content = public["data"]["terminal.json"]
        self.assertTrue(public["immutable"])
        status = self.status()
        self.assertEqual(
            (status["phase"], status["observedGeneration"]), ("Succeeded", 1)
        )
        self.assertIn(observer, status["conditions"])
        self.assertEqual(status["recoverySets"], [self.recovery])
        self.assertEqual(
            status["terminalEvidenceRef"],
            {
                "apiGroup": "",
                "kind": "ConfigMap",
                "name": self.evidence,
                "digest": digest(content.encode()),
            },
        )
        self.assertFalse(self.publish())
        self.assertEqual(self.adapter.calls, self.calls)

    def test_failed_operation_and_uncertain_status_write(self):
        self.execute("terminal-uncertain", fault="changed")
        worker = client()
        put = worker.replace_terminal_status

        def lost_response(*args, **kwargs):
            put(*args, **kwargs)
            raise TimeoutError("status response lost")

        with patch.object(worker, "replace_terminal_status", lost_response):
            try:
                self.publish(worker)
            except TimeoutError:
                pass
        self.assertEqual(self.status()["phase"], "Failed")
        retry = client()
        with patch.object(
            retry,
            "replace_terminal_status",
            side_effect=AssertionError("duplicate PUT"),
        ):
            self.assertFalse(self.publish(retry))
        self.assertEqual(self.adapter.calls, self.calls)
        self.assertTrue(self.adapter.source.exists())

    def test_recovered_operation_publishes_after_owned_cleanup(self):
        resource = retirement_resource("terminal-recovered")
        resource["spec"] = {
            "workload": resource["spec"]["workload"],
            "stages": [
                {
                    "id": "prepare",
                    "adapterRef": {"name": "local"},
                    "operation": "prepare",
                    "recoveryOperation": "clear-scratch",
                }
            ],
        }
        self.bind(resource)
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        original, scratch = root / "workload", root / "prepare.tmp"
        original.write_bytes(b"original workload")
        adapter = _LocalAdapter(root)
        engine = _engine(root, adapter, FileOperationStore(root / "operations"))

        def fail_after_prepare(request):
            scratch.write_text(request.operation)
            raise OSError("preparation interrupted")

        with patch.object(
            adapter, "execute", side_effect=fail_after_prepare
        ) as execute:
            result = run_and_retain_terminal(client(), RECORDS, self.receipt, engine)
            self.assertEqual(
                (result.status, result.stages[0].recovery_status),
                ("recovered", "succeeded"),
            )
            self.assertFalse(scratch.exists())
            self.assertTrue(self.publish())
            self.assertEqual(self.status()["phase"], "Recovered")
            self.assertFalse(self.publish())
            execute.assert_called_once()
        self.assertEqual(adapter.calls.count(("recover", "prepare")), 1)
        self.assertEqual(original.read_bytes(), b"original workload")

    def test_missing_or_recreated_evidence_cannot_close_the_operation(self):
        self.execute("terminal-evidence")
        worker = client()
        public = worker.read_terminal_evidence(LABS, self.evidence)
        key = f"configmap/{self.evidence}"
        put = worker.replace_terminal_status

        def remove_before_conflict(*args, **kwargs):
            kubectl(
                LABS,
                "annotate",
                f"continuitycontract/{self.receipt.name}",
                "test-observed=true",
            )
            kubectl(LABS, "delete", key)
            return put(*args, **kwargs)

        with patch.object(
            worker, "replace_terminal_status", side_effect=remove_before_conflict
        ) as writes:
            self.assert_refused(worker)
        writes.assert_called_once()
        for content in ("{}", public["data"]["terminal.json"]):
            replacement = worker.create_terminal_evidence(LABS, self.evidence, content)
            self.assertNotEqual(
                public["metadata"]["uid"], replacement["metadata"]["uid"]
            )
            self.assert_refused()
            kubectl(LABS, "delete", key)

    def test_terminal_status_is_not_a_receipt(self):
        self.execute("terminal-witness")
        self.assertTrue(self.publish())
        kubectl(RECORDS, "delete", f"configmap/{self.evidence}")
        self.assert_refused()

    def test_conflicting_producer_claim_is_not_published(self):
        self.execute("terminal-claims")
        self.patch_status(
            {
                "observedGeneration": 1,
                "recoverySets": [{**self.recovery, "digest": digest(b"other")}],
            }
        )
        self.assert_refused()
        self.patch_status({"recoverySets": []})
        self.assertTrue(self.publish())
        self.assertEqual(self.status()["recoverySets"], [self.recovery])
        self.assertEqual(self.adapter.calls, self.calls)


if __name__ == "__main__":
    unittest.main()
