import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from hyops.authority.models import AuthorityContext
from hyops.continuity.engine import ContinuityEngine
from hyops.continuity.models import AdapterIdentity, AdmissionResult
from hyops.continuity.storage import FileOperationStore
from hyops.controller.binding import bind_operation
from hyops.controller.client import StatusConflict, TERMINAL_FINALIZER
from hyops.controller.execution import run_bound_operation
from hyops.controller.reconcile import reconcile
from hyops.controller.references import ReferenceBindingError
from hyops.controller.terminal import run_and_retain_terminal
from hyops.controller.tests.test_terminal import TerminalFixture


class FinalizationTests(TerminalFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.meta = self.obj["metadata"]
        self.other = "other.example/keep"
        self.meta["finalizers"] = [self.other]
        self.client.replace_terminal_status.side_effect = self.write_status

    def write_status(self, ns, name, uid, version, status, **kwargs):
        self.assertEqual(
            (ns, name, uid, version),
            tuple(
                self.meta[k] for k in ("namespace", "name", "uid", "resourceVersion")
            ),
        )
        self.assertEqual(
            kwargs.get("deleting", False), "deletionTimestamp" in self.meta
        )
        self.obj["status"] = deepcopy(status)
        self.meta["resourceVersion"] = str(int(version) + 1)

    def delete(self):
        self.meta.update(
            deletionTimestamp="2026-11-28T12:00:00Z",
            generation=self.meta["generation"] + 1,
            resourceVersion=str(int(self.meta["resourceVersion"]) + 1),
        )

    def reconcile(self):
        return reconcile(self.client, "lab", "run", record_namespace="records")

    def test_orphan_finalizer_prevents_fresh_dispatch_after_rebinding(self):
        self.retain()
        self.objects.clear()
        rebound = bind_operation(self.client, "records", "lab", "run")
        self.assertNotEqual(rebound.record_uid, self.receipt.record_uid)
        self.client.create_binding.reset_mock()
        self.engine.run.reset_mock()
        for execute in (run_bound_operation, run_and_retain_terminal):
            with self.subTest(execute=execute.__name__):
                with self.assertRaisesRegex(
                    ReferenceBindingError, "^TerminalFinalizerPresent$"
                ):
                    execute(self.client, "records", rebound, self.engine)
                self.client.create_binding.assert_not_called()
                self.engine.run.assert_not_called()
                self.assertIn(TERMINAL_FINALIZER, self.meta["finalizers"])

    def test_deletion_wins_finalizer_install_race_before_dispatch(self):
        def race(*_args, **_kwargs):
            self.assertIn(("records", self.receipt.operation_id), self.objects)
            self.delete()
            raise StatusConflict

        self.client.replace_finalizers.side_effect = race
        with self.assertRaises(ReferenceBindingError):
            self.retain()
        self.engine.run.assert_not_called()
        self.client.create_terminal_evidence.assert_not_called()
        self.assertEqual(self.meta["finalizers"], [self.other])
        self.assertFalse(self.reconcile())
        self.client.replace_finalizers.assert_called_once()

    def test_guard_requires_the_owned_finalizer_at_each_mutation(self):
        def run(_contract, *, before_mutation):
            before_mutation()
            self.meta["finalizers"].remove(TERMINAL_FINALIZER)
            before_mutation()
            self.fail("mutation admitted after the finalizer was removed")

        self.engine.run.side_effect = run
        with self.assertRaises(ReferenceBindingError):
            self.retain()
        self.assertEqual(self.meta["finalizers"], [self.other])
        self.engine.run.assert_called_once()

    def test_deletion_during_admission_blocks_mutation_and_retains_failure(self):
        adapter = Mock(spec=["admit", "execute", "recover", "identity", "operations"])
        adapter.identity = AdapterIdentity("local", "test", "1", "revision")
        adapter.operations = frozenset({"save"})

        def admit(_request):
            self.assertIn(TERMINAL_FINALIZER, self.meta["finalizers"])
            self.delete()
            return AdmissionResult(allowed=True)

        adapter.admit.side_effect = admit
        generation = self.meta["generation"]
        root = Path(self.enterContext(TemporaryDirectory()))
        store = FileOperationStore(root)
        engine = ContinuityEngine(
            adapters={"local": adapter},
            authority_gate=Mock(),
            authority_context=AuthorityContext(root, root, {}),
            controller_identity=self.result.controller,
            operation_store=store,
        )
        result = run_and_retain_terminal(self.client, "records", self.receipt, engine)
        adapter.admit.assert_called_once()
        adapter.execute.assert_not_called()
        adapter.recover.assert_not_called()
        self.assertEqual(
            (result.status, result.reason_code),
            ("failed", "operation_binding_unverified"),
        )
        key = self.receipt.terminal_name
        self.assertEqual(
            self.objects["lab", key]["data"]["terminal.json"].encode(),
            store.terminal_path(result.operation_id).read_bytes(),
        )
        records = deepcopy(self.objects)
        self.reconcile()
        self.reconcile()
        self.assertEqual(self.obj["status"]["phase"], "Failed")
        self.assertEqual(self.obj["status"]["observedGeneration"], generation)
        self.assertEqual(self.meta["finalizers"], [self.other])
        self.assertEqual(self.objects, records)
        self.client.replace_terminal_status.assert_called_once()

    def test_finalizer_conflict_rechecks_other_owners_and_evidence(self):
        self.retain()
        self.publish()
        self.delete()
        self.client.replace_finalizers.reset_mock()
        records = deepcopy(self.objects)

        def contested(*args, **kwargs):
            if self.client.replace_finalizers.call_count == 1:
                self.meta["finalizers"].append("later.example/keep")
                self.meta["resourceVersion"] = str(
                    int(self.meta["resourceVersion"]) + 1
                )
                raise StatusConflict
            self.store_finalizers(*args, **kwargs)

        self.client.replace_finalizers.side_effect = contested
        self.reconcile()
        self.assertEqual(self.meta["finalizers"], [self.other, "later.example/keep"])
        self.assertEqual(self.objects, records)
        self.assertEqual(self.client.replace_finalizers.call_count, 2)
        self.engine.run.assert_called_once()

    def test_evidence_loss_during_conflict_leaves_the_finalizer(self):
        self.retain()
        self.publish()
        self.delete()

        def lose_evidence(*_args, **_kwargs):
            del self.objects["lab", self.key]
            raise StatusConflict

        self.client.replace_finalizers.reset_mock()
        self.client.replace_finalizers.side_effect = lose_evidence
        with self.assertRaises(ReferenceBindingError):
            self.reconcile()
        self.client.replace_finalizers.assert_called_once()
        self.assertIn(TERMINAL_FINALIZER, self.meta["finalizers"])
        self.engine.run.assert_called_once()

    def test_original_contract_disappears_before_release(self):
        self.retain()
        self.publish()
        self.delete()
        self.client.replace_finalizers.reset_mock()
        self.client.replace_terminal_status.reset_mock()
        self.client.read.side_effect = [deepcopy(self.obj), None, None]
        records = deepcopy(self.objects)
        self.assertFalse(self.reconcile())
        self.client.replace_terminal_status.assert_not_called()
        self.client.replace_finalizers.assert_not_called()
        self.assertEqual(self.objects, records)

    def test_replaced_or_changed_contract_cannot_release_finalizer(self):
        self.retain()
        self.publish()
        self.delete()
        self.client.replace_finalizers.reset_mock()
        for delta in (
            {"uid": "replacement"},
            {"generation": self.meta["generation"] + 1},
        ):
            with self.subTest(delta=delta), patch.dict(self.meta, delta):
                with self.assertRaises(ReferenceBindingError):
                    self.reconcile()
                self.assertIn(TERMINAL_FINALIZER, self.meta["finalizers"])
                self.client.replace_finalizers.assert_not_called()

    def test_terminal_status_without_original_records_cannot_release_finalizer(self):
        self.retain()
        self.publish()
        self.delete()
        self.client.replace_finalizers.reset_mock()
        for key in (self.receipt.record_name, self.receipt.operation_id, self.key):
            with self.subTest(record=key), patch.dict(self.objects):
                del self.objects["records", key]
                with self.assertRaises(ReferenceBindingError):
                    self.reconcile()
                self.assertIn(TERMINAL_FINALIZER, self.meta["finalizers"])
                self.client.replace_finalizers.assert_not_called()
        self.engine.run.assert_called_once()

    def test_release_conflicts_are_bounded(self):
        self.retain()
        self.publish()
        self.delete()
        self.client.replace_finalizers.reset_mock()
        self.client.replace_finalizers.side_effect = StatusConflict
        with self.assertRaises(StatusConflict):
            self.reconcile()
        self.assertEqual(self.client.replace_finalizers.call_count, 3)
        self.assertIn(TERMINAL_FINALIZER, self.meta["finalizers"])
        self.engine.run.assert_called_once()
