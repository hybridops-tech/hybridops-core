import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import yaml

from hyops.authority.models import AuthorityDeclaration, AuthorityRequirement
from hyops.continuity.api import v1alpha1
from hyops.continuity.engine import ContinuityEngine
from hyops.continuity.models import EvidenceBinding, InputBinding, WorkloadIdentity
from hyops.controller.binding import bind_operation
from hyops.controller.client import DISPATCH_ANNOTATION, ContractClient
from hyops.controller.execution import project_contract, run_bound_operation
from hyops.controller.reconcile import StatusConflict
from hyops.controller.references import ReferenceBindingError


class BoundExecutionTests(unittest.TestCase):
    def setUp(self):
        sample = (
            Path(__file__).resolve().parents[3]
            / "config/samples/continuity_v1alpha1_contract.yaml"
        )
        self.object = yaml.safe_load(sample.read_text(encoding="utf8"))
        self.name = self.object["metadata"]["name"]
        self.object["metadata"].update(
            namespace="lab", uid="contract-1", generation=1, resourceVersion="1"
        )
        spec = self.object["spec"]
        del (
            spec["workload"]["ref"],
            spec["stages"][0]["parametersRef"],
            spec["authorities"][0]["parametersRef"],
        )
        self.client = Mock(spec_set=ContractClient)
        self.records = {}
        self.client.read.side_effect = lambda *_: deepcopy(self.object)
        self.client.create_binding.side_effect = self.create_binding
        self.client.read_binding.side_effect = lambda *key: deepcopy(
            self.records.get(key)
        )
        self.engine = Mock(spec_set=ContinuityEngine)

    def create_binding(self, namespace, name, record):
        key = (namespace, name)
        if key in self.records:
            raise FileExistsError
        self.records[key] = {
            "metadata": {
                "uid": f"record-{len(self.records) + 1}",
                "namespace": namespace,
                "name": name,
                "resourceVersion": "7",
            },
            "data": {"binding.json": json.dumps(record)},
        }
        return deepcopy(self.records[key])

    def bind(self):
        receipt = bind_operation(self.client, "records", "lab", self.name)
        self.record = self.records["records", receipt.record_name]
        return receipt

    def run_bound(self, receipt):
        return run_bound_operation(self.client, "records", receipt, self.engine)

    def test_project_preserves_stage_graph_and_authority_compatibility(self):
        for compatibility in (False, True):
            with self.subTest(compatibility=compatibility):
                self.object["spec"]["authorities"][0]["compatibility"] = compatibility
                contract = project_contract(v1alpha1.decode(self.object).spec, "run-1")
                self.assertEqual(contract.operation_id, "run-1")
                self.assertEqual(
                    contract.workload,
                    WorkloadIdentity(self.name, "v1.0.0", "sha256:" + "a" * 64),
                )
                self.assertEqual(
                    contract.authorities,
                    {
                        "release-authority": AuthorityDeclaration(
                            "release-authority",
                            "release",
                            "conformance",
                            compatibility=compatibility,
                        ),
                    },
                )
                prepare, release = contract.stages
                self.assertEqual(
                    (prepare.id, prepare.adapter, prepare.operation),
                    ("prepare", "conformance", "prepare"),
                )
                self.assertEqual(prepare.recovery_operation, "remove")
                self.assertEqual(prepare.publish, {"prepared-output"})
                self.assertEqual(
                    prepare.produced_evidence, {"prepared-state": "recovery"}
                )
                self.assertTrue(release.destructive)
                self.assertEqual(release.requires, ("prepare",))
                self.assertEqual(
                    release.input_bindings,
                    {"prepared-input": InputBinding("prepare", "prepared-output")},
                )
                self.assertEqual(
                    release.evidence_bindings,
                    (EvidenceBinding("prepare", "prepared-state", "recovery"),),
                )
                self.assertEqual(
                    release.authority,
                    AuthorityRequirement("release-authority", "release", compatibility),
                )

    def test_all_reference_sites_are_rejected_before_claim(self):
        spec = self.object["spec"]
        for entry, field, kind in (
            (spec["workload"], "ref", "ConfigMap"),
            (spec["stages"][0], "parametersRef", "ConfigMap"),
            (spec["authorities"][0], "parametersRef", "Secret"),
        ):
            with self.subTest(field=field, kind=kind):
                self.object["metadata"]["uid"] = f"contract-{field}-{kind}"
                entry[field] = {"kind": kind, "name": "params"}
                secret = kind == "Secret"
                self.client.read_reference.return_value = {
                    "apiVersion": "meta.k8s.io/v1" if secret else "v1",
                    "kind": "PartialObjectMetadata" if secret else kind,
                    "metadata": {
                        "name": "params",
                        "namespace": "lab",
                        "uid": "ref-1",
                        "resourceVersion": "4",
                    },
                }
                receipt = self.bind()
                self.client.create_binding.reset_mock()
                with self.assertRaisesRegex(
                    ReferenceBindingError, "^UnsupportedExecutionReference$"
                ):
                    self.run_bound(receipt)
                self.client.create_binding.assert_not_called()
                self.client.mark_dispatch.assert_not_called()
                self.engine.run.assert_not_called()
                del entry[field]

    def test_claim_lives_on_original_binding_and_guards_each_mutation(self):
        receipt = self.bind()
        marker = {DISPATCH_ANNOTATION: receipt.operation_id}
        meta = self.record["metadata"]
        self.client.mark_dispatch.side_effect = lambda *_: meta.update(
            annotations=marker.copy(), resourceVersion="8"
        )
        self.assertIs(self.run_bound(receipt), self.engine.run.return_value)
        self.client.mark_dispatch.assert_called_once_with(
            "records", receipt.record_name, "record-1", "7", receipt.operation_id
        )
        self.assertEqual(
            self.engine.run.call_args.args[0].operation_id, receipt.operation_id
        )
        guard = self.engine.run.call_args.kwargs["before_mutation"]
        guard()
        for annotations in ({}, {DISPATCH_ANNOTATION: "different"}):
            with self.subTest(annotations=annotations):
                meta["annotations"] = annotations
                with self.assertRaisesRegex(
                    ReferenceBindingError, "^DispatchClaimChanged$"
                ):
                    guard()
        meta["annotations"] = marker
        claim_key = ("records", receipt.operation_id)
        claim = self.records[claim_key]
        for delta in (
            {"metadata": {**claim["metadata"], "uid": "replacement"}},
            {"data": {"binding.json": "{}"}},
        ):
            with self.subTest(delta=delta):
                self.records[claim_key] = {**claim, **delta}
                with self.assertRaises(ReferenceBindingError):
                    guard()
        self.records[claim_key] = claim
        self.object["metadata"]["generation"] = 2
        with self.assertRaisesRegex(ReferenceBindingError, "^ContractChanged$"):
            guard()

    def test_uncertain_claim_does_not_dispatch_or_retry_after_restart(self):
        receipt = self.bind()

        def uncertain_write(*_):
            self.record["metadata"]["annotations"] = {
                DISPATCH_ANNOTATION: receipt.operation_id
            }
            raise TimeoutError

        self.client.mark_dispatch.side_effect = uncertain_write
        with self.assertRaises(TimeoutError):
            self.run_bound(receipt)
        restarted = Mock(spec_set=ContinuityEngine)
        with self.assertRaisesRegex(ReferenceBindingError, "^DispatchAlreadyClaimed$"):
            run_bound_operation(self.client, "records", receipt, restarted)
        self.client.mark_dispatch.assert_called_once()
        self.engine.run.assert_not_called()
        restarted.run.assert_not_called()
        self.record["metadata"]["annotations"].clear()
        with self.assertRaisesRegex(ReferenceBindingError, "^DispatchAlreadyClaimed$"):
            run_bound_operation(self.client, "records", receipt, restarted)
        self.client.mark_dispatch.assert_called_once()
        restarted.run.assert_not_called()

    def test_unconfirmed_reservation_never_reaches_the_patch_or_kernel(self):
        receipt = self.bind()

        def uncertain_create(*args):
            self.create_binding(*args)
            raise TimeoutError

        self.client.create_binding.side_effect = uncertain_create
        with self.assertRaises(TimeoutError):
            self.run_bound(receipt)
        self.client.create_binding.side_effect = self.create_binding
        with self.assertRaisesRegex(ReferenceBindingError, "^DispatchAlreadyClaimed$"):
            self.run_bound(receipt)
        self.client.mark_dispatch.assert_not_called()
        self.engine.run.assert_not_called()

    def test_binding_marker_still_blocks_when_reservation_is_lost(self):
        receipt = self.bind()
        self.record["metadata"]["annotations"] = {DISPATCH_ANNOTATION: receipt.operation_id}
        self.client.create_binding.reset_mock()
        with self.assertRaisesRegex(ReferenceBindingError, "^DispatchAlreadyClaimed$"):
            self.run_bound(receipt)
        self.client.create_binding.assert_not_called()
        self.engine.run.assert_not_called()

    def test_replaced_original_binding_cannot_start_a_new_operation(self):
        receipt = self.bind()
        self.record["metadata"]["uid"] = "replacement"
        with self.assertRaisesRegex(ReferenceBindingError, "^BindingReplaced$"):
            self.run_bound(receipt)
        self.client.mark_dispatch.assert_not_called()
        self.engine.run.assert_not_called()

    def test_unsuccessful_claim_does_not_call_the_engine(self):
        for error, reported in (
            (StatusConflict(), ReferenceBindingError),
            (RuntimeError("dispatch claim was not confirmed"), RuntimeError),
            (ValueError("invalid binding ConfigMap"), ValueError),
        ):
            with self.subTest(error=error):
                self.object["metadata"]["uid"] = type(error).__name__
                receipt = self.bind()
                self.client.mark_dispatch.reset_mock()
                self.client.mark_dispatch.side_effect = error
                with self.assertRaises(reported):
                    self.run_bound(receipt)
                self.client.mark_dispatch.assert_called_once()
                self.engine.run.assert_not_called()
