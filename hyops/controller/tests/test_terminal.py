import json
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock, patch

from hyops.continuity.api import v1alpha1
from hyops.continuity.engine import ContinuityEngine
from hyops.continuity.models import ControllerIdentity, TerminalRecord
from hyops.controller.binding import bind_operation
from hyops.controller.client import (
    DISPATCH_ANNOTATION,
    TERMINAL_ANNOTATION,
    ContractClient,
)
from hyops.controller.execution import project_contract
from hyops.controller.reconcile import StatusConflict
from hyops.controller.references import ReferenceBindingError
from hyops.controller.terminal import publish_terminal_status, run_and_retain_terminal


class TerminalPublicationTests(unittest.TestCase):
    def setUp(self):
        self.obj = {
            "apiVersion": v1alpha1.API_VERSION_VALUE,
            "kind": "ContinuityContract",
            "metadata": {
                "name": "run",
                "namespace": "lab",
                "uid": "contract",
                "generation": 2,
                "resourceVersion": "5",
            },
            "spec": {
                "workload": {
                    "name": "lab",
                    "revision": "1",
                    "digest": "sha256:" + "a" * 64,
                },
                "stages": [
                    {"id": "save", "operation": "save", "adapterRef": {"name": "local"}}
                ],
            },
        }
        self.objects = {}
        self.client = Mock(spec_set=ContractClient)
        self.client.read.side_effect = lambda *_: deepcopy(self.obj)
        self.client.read_binding.side_effect = self.read_record
        self.client.read_terminal_evidence.side_effect = self.read_record
        self.client.create_binding.side_effect = lambda ns, key, val: self.create(
            ns, key, {"binding.json": json.dumps(val)}
        )
        self.client.create_terminal_evidence.side_effect = lambda ns, key, val: (
            self.create(ns, key, {"terminal.json": val})
        )
        self.client.mark_dispatch.side_effect = lambda *args: self.mark(
            DISPATCH_ANNOTATION, *args
        )
        self.client.pin_terminal_witness.side_effect = lambda *args: self.mark(
            TERMINAL_ANNOTATION, *args
        )
        self.receipt = bind_operation(self.client, "records", "lab", "run")
        contract = project_contract(
            v1alpha1.decode(self.obj).spec, self.receipt.operation_id
        )
        self.result = TerminalRecord(
            operation_id=contract.operation_id,
            contract_schema_version=contract.schema_version,
            contract_digest=contract.digest(),
            workload=contract.workload,
            controller=ControllerIdentity("core", "1", "revision"),
            status="failed",
            closure="none",
            reason_code="unknown_adapter",
            result="stage could not start",
            stages=(),
            started_at="2026-11-28T00:00:00Z",
            completed_at="2026-11-28T00:00:00Z",
        )
        self.engine = Mock(spec_set=ContinuityEngine)
        self.engine.run.return_value = self.result

    def read_record(self, ns, key):
        return deepcopy(self.objects.get((ns, key)))

    def create(self, ns, key, data):
        if (ns, key) in self.objects:
            raise FileExistsError
        obj = {
            "metadata": {"uid": f"uid-{len(self.objects)}", "resourceVersion": "1"},
            "data": data,
        }
        self.objects[ns, key] = obj
        return deepcopy(obj)

    def mark(self, annotation, ns, key, uid, version, value):
        meta = self.objects[ns, key]["metadata"]
        self.assertEqual((uid, version), (meta["uid"], meta["resourceVersion"]))
        meta.setdefault("annotations", {})[annotation] = value
        meta["resourceVersion"] = str(int(version) + 1)

    def retain(self):
        run_and_retain_terminal(self.client, "records", self.receipt, self.engine)
        self.key = self.client.create_terminal_evidence.call_args.args[1]

    def publish(self):
        return publish_terminal_status(self.client, "records", self.receipt)

    def test_existing_evidence_or_witness_stops_before_dispatch(self):
        key = "terminal-" + self.receipt.operation_id.removeprefix("dispatch-")
        for namespace in ("lab", "records"):
            with (
                self.subTest(namespace=namespace),
                patch.dict(self.objects, {(namespace, key): {}}),
            ):
                with self.assertRaisesRegex(
                    ReferenceBindingError, "^TerminalRecordAlreadyExists$"
                ):
                    self.retain()
                self.assertNotIn(("records", self.receipt.operation_id), self.objects)
        self.client.mark_dispatch.assert_not_called()
        self.engine.run.assert_not_called()

    def test_pin_conflict_revalidates_original_identities_before_retry(self):
        initial = deepcopy(self.objects)
        for change, expected_calls in (
            ("version", 2),
            ("same-pin", 1),
            ("different-pin", 1),
            ("witness-replaced", 1),
        ):
            with (
                self.subTest(change=change),
                patch.dict(self.objects, deepcopy(initial), clear=True),
            ):
                self.client.pin_terminal_witness.reset_mock()
                self.engine.run.reset_mock()

                def pin(ns, key, uid, version, expected):
                    if self.client.pin_terminal_witness.call_count == 1:
                        meta = self.objects[ns, key]["metadata"]
                        meta["resourceVersion"] = str(int(version) + 1)
                        if change.endswith("-pin"):
                            meta["annotations"][TERMINAL_ANNOTATION] = (
                                expected if change == "same-pin" else "other"
                            )
                        if change == "witness-replaced":
                            name = self.client.create_terminal_evidence.call_args.args[
                                1
                            ]
                            self.objects[ns, name]["metadata"]["uid"] = "replacement"
                        raise StatusConflict
                    self.mark(TERMINAL_ANNOTATION, ns, key, uid, version, expected)

                self.client.pin_terminal_witness.side_effect = pin
                if change in ("different-pin", "witness-replaced"):
                    with self.assertRaisesRegex(
                        ReferenceBindingError, "^TerminalWitnessChanged$"
                    ):
                        self.retain()
                else:
                    self.retain()
                self.assertEqual(
                    self.client.pin_terminal_witness.call_count, expected_calls
                )
                self.engine.run.assert_called_once()
        self.client.replace_terminal_status.assert_not_called()

    def test_persistent_pin_conflicts_stop(self):
        self.client.pin_terminal_witness.side_effect = StatusConflict
        with self.assertRaises(StatusConflict):
            self.retain()
        self.assertEqual(self.client.pin_terminal_witness.call_count, 3)
        with self.assertRaisesRegex(ReferenceBindingError, "^TerminalWitnessChanged$"):
            self.publish()
        self.engine.run.assert_called_once()

    def test_lost_response_does_not_promote_unpinned_records(self):
        initial = deepcopy(self.objects)
        key = "terminal-" + self.receipt.operation_id.removeprefix("dispatch-")
        for method, reason in (
            ("create_terminal_evidence", "TerminalWitnessMissing"),
            ("create_binding", "TerminalWitnessChanged"),
            ("pin_terminal_witness", None),
        ):
            with (
                self.subTest(method=method),
                patch.dict(self.objects, deepcopy(initial), clear=True),
            ):
                target = getattr(self.client, method)
                original = target.side_effect
                self.engine.run.reset_mock()
                self.client.replace_terminal_status.reset_mock()

                def lose_ack(*args):
                    result = original(*args)
                    if args[1] == key or method == "pin_terminal_witness":
                        raise TimeoutError
                    return result

                self.client.replace_terminal_status.side_effect = lambda *args, **_: (
                    self.obj.update(status=deepcopy(args[4]))
                )
                with (
                    patch.object(self.client, method, side_effect=lose_ack),
                    self.assertRaises(TimeoutError),
                ):
                    self.retain()
                if reason is None:
                    self.assertTrue(self.publish())
                    self.obj.pop("status")
                else:
                    with self.assertRaisesRegex(ReferenceBindingError, f"^{reason}$"):
                        self.publish()
                    self.client.replace_terminal_status.assert_not_called()
                self.engine.run.assert_called_once()

    def test_pins_raw_spec_generation_and_every_original_uid(self):
        self.retain()
        for obj, change, reason in (
            (self.obj["metadata"], {"generation": 3}, "ContractChanged"),
            (self.obj["metadata"], {"uid": "new-contract"}, "ContractChanged"),
            (self.obj["spec"], {"policy": {}}, "ContractChanged"),
            (
                self.objects["records", self.receipt.record_name]["metadata"],
                {"uid": "recreated"},
                "BindingReplaced",
            ),
            (
                self.objects["records", self.receipt.operation_id]["metadata"],
                {"uid": "recreated"},
                "DispatchClaimChanged",
            ),
            (
                self.objects["records", self.key]["metadata"],
                {"uid": "recreated"},
                "TerminalWitnessChanged",
            ),
        ):
            with self.subTest(reason=reason, change=change), patch.dict(obj, change):
                with self.assertRaisesRegex(ReferenceBindingError, f"^{reason}$"):
                    self.publish()
        self.client.replace_terminal_status.assert_not_called()
        self.engine.run.assert_called_once()

    def test_digest_covers_exact_stored_bytes(self):
        self.retain()
        data = self.objects["lab", self.key]["data"]
        data["terminal.json"] += " "
        with self.assertRaisesRegex(
            ReferenceBindingError, "^TerminalEvidenceDigestMismatch$"
        ):
            self.publish()
        self.client.replace_terminal_status.assert_not_called()

    def test_invalid_result_cannot_create_evidence_or_witness(self):
        for delta, reason in (
            ({"operation_id": "other"}, "TerminalRecordMismatch"),
            ({"contract_digest": "sha256:" + "e" * 64}, "TerminalRecordMismatch"),
            (
                {"workload": replace(self.result.workload, revision="different")},
                "TerminalRecordMismatch",
            ),
            ({"result": "x" * (1024 * 1024)}, "TerminalEvidenceTooLarge"),
        ):
            with (
                self.subTest(field=next(iter(delta))),
                patch(
                    "hyops.controller.terminal.execute_with_claim",
                    return_value=(replace(self.result, **delta), "claim"),
                ),
                patch(
                    "hyops.controller.terminal.read_dispatched_subject",
                    return_value=({"resourceVersion": "1"}, v1alpha1.decode(self.obj)),
                ),
            ):
                with self.assertRaisesRegex(ReferenceBindingError, f"^{reason}$"):
                    self.retain()
        self.client.create_terminal_evidence.assert_not_called()
        self.client.pin_terminal_witness.assert_not_called()

    def test_existing_different_terminal_status_is_not_overwritten(self):
        self.retain()
        self.obj["status"] = {
            "observedGeneration": 2,
            "phase": "Recovered",
            "terminalEvidenceRef": {
                "name": self.key,
                "kind": "ConfigMap",
                "digest": "sha256:" + "a" * 64,
            },
        }
        with self.assertRaisesRegex(ReferenceBindingError, "^TerminalStatusConflict$"):
            self.publish()
        self.client.replace_terminal_status.assert_not_called()

    def test_conflicts_are_bounded_and_reread_evidence_each_time(self):
        self.retain()
        self.client.replace_terminal_status.side_effect = StatusConflict
        self.client.read_terminal_evidence.reset_mock()
        with self.assertRaises(StatusConflict):
            self.publish()
        self.assertEqual(self.client.replace_terminal_status.call_count, 3)
        self.assertEqual(self.client.read_terminal_evidence.call_count, 3)
        self.engine.run.assert_called_once()

    def test_loss_after_put_is_not_confirmed_or_repaired(self):
        self.retain()

        def lose_evidence(_ns, _key, _uid, _version, status, **_):
            self.obj["status"] = deepcopy(status)
            del self.objects["lab", self.key]

        self.client.replace_terminal_status.side_effect = lose_evidence
        for _ in range(2):
            with self.assertRaisesRegex(
                ReferenceBindingError, "^TerminalEvidenceMissingOrReplaced$"
            ):
                self.publish()
        self.client.replace_terminal_status.assert_called_once()
        self.client.create_terminal_evidence.assert_called_once()
        self.engine.run.assert_called_once()
