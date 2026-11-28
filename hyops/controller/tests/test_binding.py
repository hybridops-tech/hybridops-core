import json
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, call, patch

from hyops.controller.binding import BindingReceipt, bind_operation, verify_operation
from hyops.controller.client import ContractClient
from hyops.controller.references import ReferenceBindingError


class BindingStoreTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=ContractClient)
        self.record = {
            "contract": {"namespace": "work", "name": "operation", "uid": "source-uid"},
            "references": [],
        }
        self.resolve = self.enterContext(
            patch("hyops.controller.binding.resolve_references")
        )
        self.resolve.return_value = self.record
        self.verify = self.enterContext(
            patch("hyops.controller.binding.verify_references")
        )
        self.stored = {
            "metadata": {"uid": "record-uid"},
            "data": {"binding.json": json.dumps(self.record)},
        }
        self.client.create_binding.return_value = self.stored
        self.client.read_binding.return_value = self.stored

    def bind(self):
        return bind_operation(self.client, "records", "work", "operation")

    def test_receipt_survives_restart_without_creating_a_record(self):
        first = self.bind()
        fresh_client = Mock(spec=ContractClient)
        fresh_client.read_binding.return_value = self.stored
        receipt = BindingReceipt(**json.loads(json.dumps(asdict(first))))
        verify_operation(fresh_client, "records", receipt)
        self.assertEqual(
            fresh_client.read_binding.call_args_list,
            [call("records", first.record_name)] * 2,
        )
        fresh_client.create_binding.assert_not_called()
        self.verify.assert_called_once_with(
            fresh_client, "work", "operation", self.record, protected=None
        )

    def test_duplicate_uses_original_record_and_refuses_drift(self):
        first = self.bind()
        self.client.create_binding.side_effect = FileExistsError
        self.resolve.return_value = {**self.record, "references": ["new observation"]}
        self.assertEqual(self.bind(), first)
        self.verify.assert_called_once_with(
            self.client, "work", "operation", self.record
        )
        self.verify.side_effect = ReferenceBindingError("ReferenceChanged")
        with self.assertRaisesRegex(ReferenceBindingError, "^ReferenceChanged$"):
            self.bind()

    def test_missing_or_replaced_baseline_cannot_be_resumed(self):
        receipt = self.bind()
        for body, reason in (
            (None, "BindingMissing"),
            ({**self.stored, "metadata": {"uid": "new-uid"}}, "BindingReplaced"),
            ({**self.stored, "data": {"binding.json": "[]"}}, "InvalidBindingRecord"),
            (
                {**self.stored, "data": {"binding.json": "private malformed data"}},
                "InvalidBindingRecord",
            ),
        ):
            with self.subTest(reason=reason):
                self.client.read_binding.return_value = body
                with self.assertRaisesRegex(ReferenceBindingError, f"^{reason}$"):
                    verify_operation(self.client, "records", receipt)
        self.assertEqual(self.client.create_binding.call_count, 1)
        self.verify.assert_not_called()

    def test_receipt_must_match_original_content_and_contract(self):
        receipt = self.bind()
        for fields in (
            {"digest": "wrong"},
            {"name": "other"},
            {"namespace": "other"},
            {"contract_uid": "other"},
        ):
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(ReferenceBindingError, "^BindingChanged$"):
                    verify_operation(self.client, "records", replace(receipt, **fields))
        self.verify.assert_not_called()

    def test_baseline_replaced_during_reference_reads_is_rejected(self):
        receipt = self.bind()
        self.client.read_binding.side_effect = [
            self.stored,
            {**self.stored, "metadata": {"uid": "replacement"}},
        ]
        with self.assertRaisesRegex(ReferenceBindingError, "^BindingReplaced$"):
            verify_operation(self.client, "records", receipt)
        self.verify.assert_called_once_with(
            self.client, "work", "operation", self.record, protected=None
        )

    def test_store_cannot_be_in_the_contract_namespace(self):
        with self.assertRaisesRegex(ReferenceBindingError, "^InvalidBindingNamespace$"):
            bind_operation(self.client, "work", "work", "operation")
        self.resolve.assert_not_called()
        self.client.create_binding.assert_not_called()

    def test_uncertain_create_does_not_fall_back_to_read_or_replacement(self):
        self.client.create_binding.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            self.bind()
        self.client.read_binding.assert_not_called()
