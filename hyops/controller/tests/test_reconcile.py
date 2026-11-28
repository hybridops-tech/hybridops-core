import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, call

import yaml

from hyops.continuity.api.v1alpha1 import decode
from hyops.controller.reconcile import StatusConflict, reconcile


_SAMPLE = Path(__file__).resolve().parents[3] / "config/samples/continuity_v1alpha1_contract.yaml"
_KEY = ("labs", "conformance-workload")
_NOW = "2026-11-28T12:00:00Z"
_LATER = "2026-11-28T13:00:00Z"
_RECOVERY = {
    "name": "workload-state",
    "evidence": "prepared-state",
    "role": "recovery",
    "digest": "sha256:" + "b" * 64,
}


def _contract():
    obj = yaml.safe_load(_SAMPLE.read_text(encoding="utf-8"))
    obj["metadata"].update(namespace=_KEY[0], uid="original", resourceVersion="71", generation=1)
    return obj


def _client(*snapshots):
    client = Mock(spec_set=["read", "replace_status"])
    client.read.side_effect = snapshots
    return client


def _run(client, when=_NOW):
    return reconcile(client, *_KEY, now=lambda: when)


def _condition(status):
    [condition] = [c for c in status["conditions"] if c["type"] == "ContractValid"]
    return condition


class StatusReconciliationTests(unittest.TestCase):
    def test_only_writes_status_with_the_read_identity(self):
        obj = _contract()
        previous = deepcopy(obj)
        client = _client(obj)
        self.assertTrue(_run(client))

        client.read.assert_called_once_with(*_KEY)
        client.replace_status.assert_called_once()
        ns, name, uid, version, status = client.replace_status.call_args.args
        self.assertEqual((ns, name, uid, version), (*_KEY, "original", "71"))
        self.assertEqual(obj, previous)
        self.assertEqual(status["phase"], "Pending")
        self.assertEqual(status["observedGeneration"], 1)
        condition = _condition(status)
        self.assertEqual(condition["status"], "True")
        self.assertEqual(condition["observedGeneration"], 1)
        self.assertEqual(condition["lastTransitionTime"], _NOW)
        decode(dict(obj, status=status))

    def test_duplicate_delivery_and_restart_use_persisted_status(self):
        obj = _contract()
        client = _client(obj)
        self.assertTrue(_run(client))
        obj["status"] = deepcopy(client.replace_status.call_args.args[-1])
        obj["metadata"]["resourceVersion"] = "72"
        client.read.side_effect = [deepcopy(obj)]
        self.assertFalse(_run(client, _LATER))
        self.assertEqual(client.replace_status.call_count, 1)

        restarted = _client(deepcopy(obj))
        self.assertFalse(_run(restarted, _LATER))
        restarted.replace_status.assert_not_called()

    def test_generation_change_preserves_other_status_and_transition_time(self):
        obj = _contract()
        first = _client(obj)
        _run(first)
        status = deepcopy(first.replace_status.call_args.args[-1])
        other = dict(_condition(status), type="InventoryReady", reason="InventoryRecorded")
        status["conditions"].append(other)
        status["recoverySets"] = [_RECOVERY.copy()]
        obj["status"] = status
        obj["metadata"].update(resourceVersion="73", generation=2)
        obj["spec"]["workload"]["revision"] = "v2"
        client = _client(obj)
        self.assertTrue(_run(client, _LATER))
        result = client.replace_status.call_args.args[-1]
        self.assertIn(other, result["conditions"])
        self.assertEqual(result["recoverySets"], [_RECOVERY])
        self.assertEqual(_condition(result)["observedGeneration"], 2)
        self.assertEqual(_condition(result)["lastTransitionTime"], _NOW)

    def test_invalid_spec_publishes_diagnostic_without_echoing_input(self):
        obj = _contract()
        obj["spec"]["sensitive-user-input"] = "must-not-enter-status"
        client = _client(obj)
        self.assertTrue(_run(client))
        result = client.replace_status.call_args.args[-1]
        condition = _condition(result)
        self.assertEqual(condition["status"], "False")
        self.assertEqual(condition["reason"], "UnknownField")
        self.assertNotIn("sensitive-user-input", str(result))
        self.assertNotIn("must-not-enter-status", str(result))
        del obj["spec"]["sensitive-user-input"]
        obj["status"] = result
        obj["metadata"].update(resourceVersion="72", generation=2)
        corrected = _client(obj)
        self.assertTrue(_run(corrected, _LATER))
        condition = _condition(corrected.replace_status.call_args.args[-1])
        self.assertEqual(condition["status"], "True")
        self.assertEqual(condition["lastTransitionTime"], _LATER)

    def test_validation_write_preserves_unowned_status_representation(self):
        obj = _contract()
        declaration = obj["spec"]["recoverySets"][0]
        obj["spec"]["recoverySets"].append({
            "name": "another-state",
            "producer": dict(declaration["producer"], evidence="another-evidence"),
        })
        other = {
            "type": "ZonalReady", "status": "True", "lastTransitionTime": _NOW,
            "reason": "Observed", "message": "Observed.",
        }
        second = dict(other, type="AccessReady", observedGeneration=0)
        claims = [_RECOVERY.copy(), dict(_RECOVERY, name="another-state", evidence="another-evidence")]
        for exists in (False, True):
            with self.subTest(existing_condition=exists):
                conditions = [other, second]
                if exists:
                    conditions.insert(1, dict(other, type="ContractValid", status="False"))
                obj["status"] = {"conditions": conditions, "recoverySets": claims}
                before = deepcopy(obj["status"])
                client = _client(obj)
                self.assertTrue(_run(client, _LATER))
                self.assertEqual(obj["status"], before)
                result = client.replace_status.call_args.args[-1]
                owned = _condition(result)
                expected = [other, owned, second] if exists else [other, second, owned]
                self.assertEqual(result, dict(before, conditions=expected, observedGeneration=1))

    def test_missing_or_deleting_resource_is_not_written(self):
        deleting = _contract()
        deleting["metadata"]["deletionTimestamp"] = _NOW
        for obj in (None, deleting):
            with self.subTest(obj_exists=obj is not None):
                client = _client(obj)
                self.assertFalse(_run(client))
                client.replace_status.assert_not_called()

    def test_malformed_or_foreign_resource_never_writes(self):
        for key, value in (
            ("uid", None),
            ("resourceVersion", ""),
            ("generation", False),
            ("namespace", "another-namespace"),
            ("name", "another-contract"),
        ):
            with self.subTest(key=key):
                obj = _contract()
                obj["metadata"][key] = value
                client = _client(obj)
                with self.assertRaises(ValueError):
                    _run(client)
                client.replace_status.assert_not_called()
        obj = _contract()
        obj["kind"] = "ConfigMap"
        client = _client(obj)
        with self.assertRaises(ValueError):
            _run(client)
        client.replace_status.assert_not_called()

    def test_unreadable_persisted_status_is_not_replaced(self):
        obj = _contract()
        obj["status"] = {"conditions": "not-a-list"}
        client = _client(obj)
        with self.assertRaises(ValueError):
            _run(client)
        client.replace_status.assert_not_called()

    def test_invalid_spec_cannot_discard_existing_recovery_evidence(self):
        obj = _contract()
        obj["spec"]["stages"].clear()
        obj["status"] = {
            "observedGeneration": 1,
            "phase": "Pending",
            "recoverySets": [_RECOVERY.copy()],
        }
        client = _client(obj)
        with self.assertRaises(ValueError):
            _run(client)
        client.replace_status.assert_not_called()

    def test_full_condition_list_is_not_evicted_to_make_room(self):
        obj = _contract()
        obj["status"] = {
            "observedGeneration": 1,
            "conditions": [
                {
                    "type": f"Other{i}",
                    "status": "True",
                    "observedGeneration": 1,
                    "lastTransitionTime": _NOW,
                    "reason": "Recorded",
                    "message": "Observed.",
                }
                for i in range(32)
            ],
        }
        decode(obj)
        client = _client(obj)
        with self.assertRaises(ValueError):
            _run(client)
        client.replace_status.assert_not_called()

    def test_conflict_revalidates_the_latest_spec(self):
        original = _contract()
        updated = deepcopy(original)
        updated["metadata"].update(resourceVersion="75", generation=2)
        updated["spec"]["stages"].clear()
        client = _client(original, updated)
        client.replace_status.side_effect = [StatusConflict(), None]
        self.assertTrue(_run(client))
        self.assertEqual(client.read.call_args_list, [call(*_KEY), call(*_KEY)])
        first, second = (attempt.args for attempt in client.replace_status.call_args_list)
        self.assertEqual((first[3], _condition(first[4])["status"]), ("71", "True"))
        self.assertEqual((second[3], _condition(second[4])["status"]), ("75", "False"))
        self.assertEqual(second[4]["observedGeneration"], 2)

    def test_conflict_does_not_overwrite_terminal_status_or_recreated_resource(self):
        original = _contract()
        terminal = deepcopy(original)
        terminal["metadata"]["resourceVersion"] = "73"
        terminal["status"] = {
            "observedGeneration": 1,
            "phase": "Failed",
            "terminalEvidenceRef": {
                "kind": "ConfigMap",
                "name": "terminal",
                "digest": "sha256:" + "c" * 64,
            },
        }
        decode(terminal)
        replacement = deepcopy(original)
        replacement["metadata"].update(resourceVersion="74", uid="replacement")
        for state, latest in (
            ("terminal", terminal),
            ("recreated", replacement),
            ("deleted", None),
        ):
            with self.subTest(state=state):
                client = _client(original, latest)
                client.replace_status.side_effect = StatusConflict
                self.assertFalse(_run(client))
                client.replace_status.assert_called_once()

        terminal["metadata"]["generation"] = 2
        client = _client(terminal)
        with self.assertRaises(ValueError):
            _run(client)
        client.replace_status.assert_not_called()

    def test_repeated_conflicts_are_bounded_and_reported(self):
        client = _client(*[_contract() for _ in range(3)])
        client.replace_status.side_effect = StatusConflict
        with self.assertRaises(StatusConflict):
            _run(client)
        self.assertEqual(client.replace_status.call_count, 3)
        self.assertEqual(client.read.call_count, 3)
