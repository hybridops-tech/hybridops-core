import unittest
from copy import deepcopy

from hyops.continuity.api import v1alpha1
from hyops.controller.references import ReferenceBindingError
from hyops.controller.terminal_projection import terminal_status


DIGEST = "sha256:" + "a" * 64
RECORD_DIGEST = "sha256:" + "b" * 64


def step(name, *, status="succeeded", recovery="not_required", evidence=()):
    return {
        "stage_id": name,
        "operation": name,
        "adapter": {"name": "local"},
        "status": status,
        "recovery_status": recovery,
        "evidence": list(evidence),
    }


def record(status, closure, *stages):
    return {
        "kind": "ContinuityOperationRecord",
        "schema_version": "1",
        "status": status,
        "closure": closure,
        "stages": list(stages),
    }


class TerminalProjectionTests(unittest.TestCase):
    def setUp(self):
        self.condition = {
            "type": "ContractValid",
            "status": "True",
            "reason": "Validated",
            "message": "Contract specification is valid.",
            "observedGeneration": 3,
            "lastTransitionTime": "2026-11-28T12:00:00Z",
        }
        self.obj = {
            "apiVersion": v1alpha1.API_VERSION_VALUE,
            "kind": "ContinuityContract",
            "metadata": {"name": "run", "namespace": "lab", "generation": 3},
            "spec": {
                "workload": {"name": "workload", "revision": "1", "digest": DIGEST},
                "stages": [
                    {
                        "id": name,
                        "operation": name,
                        "adapterRef": {"name": "local"},
                        **fields,
                    }
                    for name, fields in (
                        ("capture", {"recoveryOperation": "remove"}),
                        ("finish", {"requires": ["capture"]}),
                    )
                ],
                "recoverySets": [
                    {
                        "name": "saved",
                        "producer": {
                            "stage": "capture",
                            "evidence": "snapshot",
                            "role": "recovery",
                        },
                    }
                ],
            },
            "status": {"observedGeneration": 3, "conditions": [self.condition]},
        }
        self.item = {"name": "snapshot", "role": "recovery", "digest": DIGEST}
        self.identity = {
            "name": "saved",
            "evidence": "snapshot",
            "role": "recovery",
            "digest": DIGEST,
        }

    def project(self, value):
        return terminal_status(
            v1alpha1.decode(self.obj), value, "terminal-1", RECORD_DIGEST
        )

    def test_all_terminal_outcomes_preserve_conditions_and_use_producer_identities(
        self,
    ):
        capture = step("capture", evidence=[self.item])
        for phase, value, sets in (
            (
                "Succeeded",
                record("succeeded", "completed", capture, step("finish")),
                [self.identity],
            ),
            (
                "Recovered",
                record(
                    "recovered",
                    "recovered",
                    {**capture, "recovery_status": "succeeded"},
                    step("finish", status="denied"),
                ),
                [self.identity],
            ),
            (
                "Failed",
                record(
                    "failed",
                    "recovery_failed",
                    {**capture, "recovery_status": "blocked"},
                    step("finish", status="denied"),
                ),
                [self.identity],
            ),
            ("Failed", record("failed", "none", step("capture", status="failed")), []),
            ("Failed", record("failed", "none"), []),
            (
                "Recovered",
                record(
                    "recovered",
                    "recovered",
                    step("capture", status="failed", recovery="succeeded"),
                ),
                [],
            ),
            (
                "Failed",
                record(
                    "failed",
                    "recovery_failed",
                    {**capture, "recovery_status": "blocked"},
                    step("finish", recovery="not_declared"),
                ),
                [self.identity],
            ),
        ):
            with self.subTest(phase=phase, closure=value["closure"], sets=sets):
                projected = self.project(value)
                self.assertEqual(
                    projected,
                    {
                        "phase": phase,
                        "observedGeneration": 3,
                        "conditions": [self.condition],
                        "recoverySets": sets,
                        "terminalEvidenceRef": {
                            "apiGroup": "",
                            "kind": "ConfigMap",
                            "name": "terminal-1",
                            "digest": RECORD_DIGEST,
                        },
                    },
                )
                prior = self.obj["status"]
                self.obj["status"] = projected
                try:
                    self.assertEqual(self.project(value), projected)
                finally:
                    self.obj["status"] = prior

    def test_prior_status_claim_cannot_replace_producer_evidence(self):
        self.obj["status"]["recoverySets"] = [
            {**self.identity, "digest": RECORD_DIGEST}
        ]
        for value in (
            record(
                "succeeded",
                "completed",
                step("capture", evidence=[self.item]),
                step("finish"),
            ),
            record("failed", "none"),
        ):
            with (
                self.subTest(status=value["status"]),
                self.assertRaisesRegex(ReferenceBindingError, "RecoverySetConflict"),
            ):
                self.project(value)

    def test_invalid_projection_is_refused(self):
        capture = step("capture", evidence=[self.item])
        good = record("succeeded", "completed", capture, step("finish"))
        for value in (
            {**good, "schema_version": "2"},
            {**good, "kind": "OtherRecord"},
            {**good, "status": "running"},
            {**good, "closure": "recovered"},
            {**good, "stages": None},
            record("succeeded", "completed", capture),
            record("succeeded", "completed", capture, capture, step("finish")),
            record("succeeded", "completed", step("capture"), step("finish")),
            record("failed", "none", step("unknown", status="failed")),
            record(
                "recovered",
                "recovered",
                {**capture, "recovery_status": "blocked"},
                step("finish", status="failed", recovery="succeeded"),
            ),
            record("recovered", "recovered", capture, step("finish")),
            record(
                "failed", "none", step("capture", status="failed", evidence=[self.item])
            ),
            record("failed", "recovery_failed"),
        ):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ReferenceBindingError, "InvalidTerminalRecord"),
            ):
                self.project(value)
        for items in (
            None,
            [self.item, self.item],
            [{**self.item, "role": "other"}],
            [{**self.item, "digest": "wrong"}],
        ):
            value = deepcopy(good)
            value["stages"][0]["evidence"] = items
            with (
                self.subTest(evidence=items),
                self.assertRaisesRegex(ReferenceBindingError, "InvalidTerminalRecord"),
            ):
                self.project(value)
