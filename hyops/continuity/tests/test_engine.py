from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from unittest.mock import patch

import hyops.continuity.storage as continuity_storage
from hyops.authority.models import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityProviderIdentity,
    AuthorityReceipt,
    AuthorityRequirement,
)
from hyops.authority.registry import AuthorityProviderRegistry
from hyops.authority.resolver import AuthorityResolver
from hyops.continuity import (
    AdapterIdentity,
    AdapterRequest,
    AdmissionResult,
    ContinuityContract,
    ContinuityEngine,
    ControllerIdentity,
    EvidenceBinding,
    EvidenceIdentity,
    ExecutionResult,
    InputBinding,
    RecoveryRequest,
    RecoveryResult,
    StageSpec,
    TerminalPersistenceError,
    WorkloadIdentity,
)
from hyops.continuity.errors import ContractFailure
from hyops.continuity.storage import (
    FileOperationStore,
    OperationLease,
    PublicationState,
)


class _AuthorityProvider:
    name = "local"
    capabilities = frozenset({"continuity"})

    def validate_configuration(self, declaration, context) -> None:
        if declaration.config.get("ready") is not True:
            raise ValueError("authority is not ready")

    def evaluate(self, declaration, context) -> AuthorityEvaluation:
        if declaration.config.get("error") is True:
            raise RuntimeError("provider detail must not escape")
        return AuthorityEvaluation(
            healthy=True,
            state="ready",
            result="token=authority-secret",
            instance="conformance",
            endpoint="https://authority-secret.invalid",
            revision="1",
            freshness={"token": "freshness-secret"},
        )


class _Adapter:
    def __init__(self, name: str = "local") -> None:
        self.identity = AdapterIdentity(
            name=name,
            distribution="hybridops-conformance",
            version="1.0.0",
            revision="test-adapter",
        )
        self.operations = frozenset({"prepare", "release", "remove"})
        self.calls: list[tuple[str, str]] = []
        self.denied_operations: set[str] = set()
        self.recovery_succeeds = True
        self.omit_prepare_output = False
        self.omit_prepare_evidence = False
        self.prepare_evidence_override: tuple[EvidenceIdentity, ...] | None = None
        self.execute_errors: set[str] = set()
        self.execute_entered: threading.Event | None = None
        self.execute_continue: threading.Event | None = None
        self.mutate_contract_on_execute = False
        self.mutate_authority_on_execute = False
        self.mutate_evidence_on_release = False
        self.mutate_outputs_on_release = False
        self.mutate_request_on_release = False
        self.return_non_json_outputs = False
        self.retained_evidence: EvidenceIdentity | None = None
        self.retained_execution: ExecutionResult | None = None
        self.retained_request: AdapterRequest | None = None
        self.recovery_outputs: dict[str, dict[str, object]] = {}
        self.recovery_requests: dict[str, RecoveryRequest] = {}

    def admit(self, request: AdapterRequest) -> AdmissionResult:
        self.calls.append(("admit", request.stage_id))
        if request.operation in self.denied_operations:
            return AdmissionResult(
                allowed=False,
                reason_code="release_denied",
            )
        return AdmissionResult(allowed=True)

    def execute(self, request: AdapterRequest) -> ExecutionResult:
        self.calls.append(("execute", request.stage_id))
        if request.operation == "prepare":
            self.retained_request = request
        if self.mutate_contract_on_execute:
            object.__setattr__(self.identity, "revision", "mutated-adapter")
            self.operations = frozenset({"mutated"})
        if self.mutate_authority_on_execute and request.authority_receipt is not None:
            object.__setattr__(
                request.authority_receipt.provider_identity,
                "version",
                "mutated-provider",
            )
            object.__setattr__(
                request.authority_receipt.provider_identity,
                "entry_point",
                "mutated:provider",
            )
        if self.mutate_evidence_on_release and self.retained_evidence is not None:
            object.__setattr__(self.retained_evidence, "name", "mutated-evidence")
            object.__setattr__(self.retained_evidence, "digest", "sha256:" + "b" * 64)
        if (
            request.operation == "release"
            and self.mutate_outputs_on_release
            and self.retained_execution is not None
        ):
            object.__setattr__(
                self.retained_execution,
                "outputs",
                {"artifact": "mutated-artifact"},
            )
        if (
            request.operation == "release"
            and self.mutate_request_on_release
            and self.retained_request is not None
        ):
            object.__setattr__(self.retained_request, "operation_id", "mutated-run")
            object.__setattr__(self.retained_request, "stage_id", "mutated-stage")
            object.__setattr__(self.retained_request, "operation", "mutated-operation")
            object.__setattr__(
                self.retained_request,
                "inputs",
                {"source": "mutated-source"},
            )
        if self.execute_entered is not None:
            self.execute_entered.set()
        if self.execute_continue is not None:
            self.execute_continue.wait(timeout=5)
        if request.operation in self.execute_errors:
            raise RuntimeError("adapter detail must not escape")
        if request.operation == "prepare":
            if self.omit_prepare_output:
                return ExecutionResult(outputs={"private": "not-published"})
            artifact = f"artifact:{request.inputs['source']}"
            default_evidence = (
                EvidenceIdentity(
                    name="recovery-set",
                    role="recovery_set",
                    digest=("sha256:" + hashlib.sha256(artifact.encode()).hexdigest()),
                ),
            )
            self.retained_evidence = default_evidence[0]
            execution = ExecutionResult(
                outputs={
                    "artifact": artifact,
                    "private": "not-published",
                },
                evidence=(
                    ()
                    if self.omit_prepare_evidence
                    else self.prepare_evidence_override or default_evidence
                ),
            )
            if self.return_non_json_outputs:
                object.__setattr__(execution, "outputs", {"artifact": object()})
            self.retained_execution = execution
            return execution
        return ExecutionResult(
            outputs={"receipt": f"released:{request.inputs['artifact']}"},
        )

    def recover(self, request: RecoveryRequest) -> RecoveryResult:
        self.calls.append(("recover", request.stage_id))
        self.recovery_requests[request.stage_id] = request
        self.recovery_outputs[request.stage_id] = dict(request.outputs)
        return RecoveryResult(
            succeeded=self.recovery_succeeds,
            reason_code="" if self.recovery_succeeds else "remove_failed",
        )


class _ExplodingOperations(frozenset[str]):
    def __iter__(self):
        raise RuntimeError("adapter metadata failure")


class _FailAcquireStore:
    def acquire(self, operation_id, claim):
        raise PermissionError("evidence store is unavailable")

    def publish(self, lease, record) -> None:
        raise AssertionError("publish must not be called")

    def probe(self, lease, record):
        raise AssertionError("probe must not be called")


class _FailOncePublishStore:
    def __init__(self, root: Path) -> None:
        self.delegate = FileOperationStore(root)
        self.publish_attempts = 0

    def acquire(self, operation_id, claim):
        return self.delegate.acquire(operation_id, claim)

    def publish(self, lease: OperationLease, record) -> None:
        self.publish_attempts += 1
        if self.publish_attempts == 1:
            raise RuntimeError("terminal write failed")
        self.delegate.publish(lease, record)

    def probe(self, lease: OperationLease, record) -> PublicationState:
        return self.delegate.probe(lease, record)


class _WriteThenRaiseStore:
    def __init__(self, root: Path) -> None:
        self.delegate = FileOperationStore(root)

    def acquire(self, operation_id, claim):
        return self.delegate.acquire(operation_id, claim)

    def publish(self, lease: OperationLease, record) -> None:
        self.delegate.publish(lease, record)
        raise PermissionError("terminal acknowledgement failed")

    def probe(self, lease: OperationLease, record) -> PublicationState:
        return self.delegate.probe(lease, record)


class _UnknownPublishStore:
    def __init__(self, root: Path) -> None:
        self.delegate = FileOperationStore(root)

    def acquire(self, operation_id, claim):
        return self.delegate.acquire(operation_id, claim)

    def publish(self, lease: OperationLease, record) -> None:
        raise RuntimeError("terminal publication outcome is unavailable")

    def probe(self, lease: OperationLease, record) -> PublicationState:
        return PublicationState.UNKNOWN


class _ConflictPublishStore(_UnknownPublishStore):
    def probe(self, lease: OperationLease, record) -> PublicationState:
        return PublicationState.CONFLICT


class _ReceiptGate:
    def __init__(self, receipt: AuthorityReceipt) -> None:
        self.receipt = receipt

    def enforce(self, requirement, declarations, context) -> AuthorityReceipt:
        return self.receipt


class ContinuityEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.adapter = _Adapter()
        self.workload = WorkloadIdentity(
            name="test-workload",
            revision="test-revision",
            digest="sha256:" + "a" * 64,
        )
        self.controller = ControllerIdentity(
            distribution="hybridops-core",
            version="test",
            revision="test-source",
        )
        registry = AuthorityProviderRegistry()
        registry.register(
            _AuthorityProvider(),
            identity=AuthorityProviderIdentity(
                source="direct",
                distribution="hybridops-conformance",
                version="1.0.0",
                entry_point="tests:_AuthorityProvider",
            ),
        )
        self.authority_gate = AuthorityResolver(registry)
        self.authority_context = AuthorityContext(
            runtime_root=self.root,
            state_root=self.root,
            env={},
        )
        ticks = count()
        self.clock = lambda: (
            datetime(2026, 11, 27, 12, 0, tzinfo=UTC) + timedelta(seconds=next(ticks))
        )
        self.store = FileOperationStore(self.root / "operations")
        self.engine = self._engine()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _engine(
        self,
        *,
        adapter: _Adapter | None = None,
        operation_store=None,
        authority_gate=None,
    ) -> ContinuityEngine:
        return ContinuityEngine(
            adapters={"local": adapter if adapter is not None else self.adapter},
            authority_gate=authority_gate or self.authority_gate,
            authority_context=self.authority_context,
            controller_identity=self.controller,
            operation_store=(
                operation_store if operation_store is not None else self.store
            ),
            clock=self.clock,
        )

    def _terminal_path(self, operation_id: str = "test-run") -> Path:
        return self.store.terminal_path(operation_id)

    def _spec(self) -> ContinuityContract:
        requirement = AuthorityRequirement(
            logical_ref="release-authority",
            capability="continuity",
        )
        declaration = AuthorityDeclaration(
            logical_ref="release-authority",
            capability="continuity",
            provider="local",
            config={"ready": True},
        )
        return ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            authorities={"release-authority": declaration},
            stages=(
                StageSpec(
                    id="prepare",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "lab-a"},
                    publish=frozenset({"artifact"}),
                    recovery_operation="remove",
                ),
                StageSpec(
                    id="release",
                    adapter="local",
                    operation="release",
                    requires=("prepare",),
                    input_bindings={
                        "artifact": InputBinding(
                            stage="prepare",
                            output="artifact",
                        )
                    },
                    publish=frozenset({"receipt"}),
                    evidence_bindings=(
                        EvidenceBinding(
                            stage="prepare",
                            name="recovery-set",
                            role="recovery_set",
                        ),
                    ),
                    authority=requirement,
                ),
            ),
        )

    def test_executes_in_dependency_order_and_writes_terminal_record(self) -> None:
        record_path = self._terminal_path()

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.closure, "completed")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("admit", "release"),
                ("execute", "release"),
            ],
        )
        evidence = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], "1")
        self.assertEqual(evidence["status"], "succeeded")
        self.assertEqual(evidence["contract"]["digest"], self._spec().digest())
        self.assertEqual(evidence["controller"], self.controller.to_evidence())
        self.assertEqual(evidence["workload"], self.workload.to_evidence())
        self.assertEqual(
            evidence["stages"][0]["evidence"][0]["role"],
            "recovery_set",
        )
        self.assertNotIn("evidence", evidence)
        self.assertEqual(evidence["stages"][0]["outputs"][0]["name"], "artifact")
        self.assertTrue(
            evidence["stages"][0]["outputs"][0]["digest"].startswith("sha256:")
        )
        self.assertEqual(
            evidence["stages"][0]["adapter_operations"],
            ["prepare", "release", "remove"],
        )
        self.assertNotIn("artifact:lab-a", record_path.read_text(encoding="utf-8"))
        self.assertNotIn("not-published", record_path.read_text(encoding="utf-8"))
        self.assertEqual(
            evidence["stages"][1]["authority_receipt"]["provider"],
            "local",
        )
        self.assertEqual(
            evidence["stages"][1]["authority_receipt"]["provider_identity"],
            {
                "source": "direct",
                "distribution": "hybridops-conformance",
                "version": "1.0.0",
                "entry_point": "tests:_AuthorityProvider",
                "contract_version": "1",
            },
        )
        self.assertNotIn("authority-secret", record_path.read_text(encoding="utf-8"))
        self.assertNotIn("freshness-secret", record_path.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(record_path.stat().st_mode), 0o600)

    def test_terminal_uses_adapter_contract_validated_before_execution(self) -> None:
        self.adapter.mutate_contract_on_execute = True

        result = self.engine.run(self._spec())

        for stage in result.stages:
            self.assertEqual(stage.adapter.revision, "test-adapter")
            self.assertEqual(
                stage.adapter_operations,
                ("prepare", "release", "remove"),
            )
        evidence = json.loads(self._terminal_path().read_text(encoding="utf-8"))
        self.assertEqual(
            evidence["stages"][0]["adapter"]["revision"],
            "test-adapter",
        )
        self.assertEqual(
            evidence["stages"][0]["adapter_operations"],
            ["prepare", "release", "remove"],
        )

    def test_adapter_metadata_failure_closes_without_adapter_calls(self) -> None:
        self.adapter.operations = _ExplodingOperations(
            {"prepare", "release", "remove"}
        )

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason_code, "invalid_adapter_contract")
        self.assertEqual(result.stages, ())
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(self._terminal_path().is_file())

    def test_terminal_uses_authority_provenance_validated_before_execution(
        self,
    ) -> None:
        self.adapter.mutate_authority_on_execute = True

        result = self.engine.run(self._spec())

        authority = result.stages[1].authority_receipt
        self.assertIsNotNone(authority)
        assert authority is not None
        self.assertEqual(authority.provider_identity.version, "1.0.0")
        self.assertEqual(
            authority.provider_identity.entry_point,
            "tests:_AuthorityProvider",
        )

    def test_terminal_uses_evidence_validated_before_later_mutation(self) -> None:
        self.adapter.mutate_evidence_on_release = True

        result = self.engine.run(self._spec())

        prepared_evidence = result.stages[0].evidence[0]
        self.assertEqual(prepared_evidence.name, "recovery-set")
        self.assertEqual(prepared_evidence.role, "recovery_set")
        self.assertNotEqual(prepared_evidence.digest, "sha256:" + "b" * 64)

    def test_recovery_uses_request_and_outputs_snapshotted_before_mutation(
        self,
    ) -> None:
        self.adapter.mutate_outputs_on_release = True
        self.adapter.mutate_request_on_release = True
        self.adapter.execute_errors.add("release")
        spec = self._spec()
        spec = replace(
            spec,
            stages=(
                spec.stages[0],
                replace(spec.stages[1], recovery_operation="remove"),
            ),
        )

        result = self.engine.run(spec)

        self.assertEqual(result.status, "recovered")
        self.assertEqual(
            self.adapter.recovery_outputs["prepare"]["artifact"],
            "artifact:lab-a",
        )
        recovery_request = self.adapter.recovery_requests["prepare"]
        self.assertEqual(recovery_request.operation_id, "test-run")
        self.assertEqual(recovery_request.stage_id, "prepare")
        self.assertEqual(recovery_request.operation, "prepare")
        self.assertEqual(recovery_request.inputs, {"source": "lab-a"})

    def test_non_json_outputs_fail_closed_and_recover(self) -> None:
        self.adapter.return_non_json_outputs = True

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "invalid_stage_outputs")
        self.assertEqual(self.adapter.recovery_outputs["prepare"], {})
        self.assertTrue(self._terminal_path().is_file())

    def test_unencodable_published_output_recovers_and_writes_terminal(self) -> None:
        filename = os.fsdecode(b"private-filename-\xff")
        spec = self._spec()
        prepare, release = spec.stages
        spec = replace(
            spec, stages=(prepare, replace(release, recovery_operation="remove"))
        )
        execute = self.adapter.execute

        def execute_with_filename(request: AdapterRequest) -> ExecutionResult:
            result = execute(request)
            if request.stage_id == "release":
                return replace(result, outputs={"receipt": {"files": [filename]}})
            return result

        with patch.object(self.adapter, "execute", side_effect=execute_with_filename):
            result = self.engine.run(spec)

        self.assertEqual(result.reason_code, "invalid_stage_outputs")
        self.assertEqual(result.closure, "recovered")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("admit", "release"),
                ("execute", "release"),
                ("recover", "release"),
                ("recover", "prepare"),
            ],
        )
        terminal = self._terminal_path().read_text(encoding="utf-8")
        self.assertNotIn("private-filename", terminal)
        self.assertEqual(json.loads(terminal), result.to_evidence())
        self.assertEqual(result.stages[1].status, "failed")
        self.assertEqual(result.stages[1].outputs, ())
        self.assertEqual(result.stages[1].recovery_status, "succeeded")

    def test_denied_release_recovers_prepared_stage_without_second_mutation(
        self,
    ) -> None:
        self.adapter.denied_operations.add("release")

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "adapter_admission_denied")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("admit", "release"),
                ("recover", "prepare"),
            ],
        )
        self.assertEqual(result.stages[0].recovery_status, "succeeded")
        self.assertEqual(result.stages[1].status, "denied")
        self.assertEqual(result.stages[1].adapter_reason_code, "release_denied")

    def test_recovery_failure_is_terminal(self) -> None:
        self.adapter.denied_operations.add("release")
        self.adapter.recovery_succeeds = False

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.closure, "recovery_failed")
        self.assertEqual(result.stages[0].recovery_status, "failed")
        self.assertEqual(
            result.stages[0].recovery_reason_code,
            "adapter_recovery_failed",
        )
        self.assertEqual(
            result.stages[0].adapter_recovery_reason_code,
            "remove_failed",
        )

    def test_invalid_contract_is_rejected_before_adapter_calls(self) -> None:
        spec = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(
                StageSpec(
                    id="release",
                    adapter="local",
                    operation="release",
                    requires=("missing",),
                ),
            ),
        )

        result = self.engine.run(spec)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.closure, "none")
        self.assertEqual(result.reason_code, "unknown_dependency")
        self.assertEqual(self.adapter.calls, [])

    def test_structurally_invalid_contract_is_rejected_before_claim(self) -> None:
        with self.assertRaises(ContractFailure) as invalid_type:
            self.engine.run(object())

        self.assertEqual(invalid_type.exception.reason_code, "invalid_contract")
        malformed = replace(
            self._spec(),
            operation_id="malformed-run",
            stages=({"id": "prepare"},),
        )
        with self.assertRaises(ContractFailure) as invalid_stage:
            self.engine.run(malformed)

        self.assertEqual(invalid_stage.exception.reason_code, "invalid_contract")
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse((self.root / "operations").exists())

    def test_invalid_nested_contract_shapes_are_rejected_before_claim(self) -> None:
        base = self._spec()
        invalid_contracts = (
            (
                replace(base, workload=object()),
                "invalid_workload_identity",
            ),
            (
                replace(
                    base,
                    stages=(
                        replace(
                            base.stages[0],
                            produced_evidence={"bad/name": "recovery_set"},
                        ),
                    ),
                ),
                "invalid_contract",
            ),
            (
                replace(
                    base,
                    stages=(
                        replace(base.stages[0], produced_evidence={"snapshot": None}),
                    ),
                ),
                "invalid_contract",
            ),
            (
                replace(
                    base,
                    stages=(
                        base.stages[0],
                        replace(
                            base.stages[1],
                            input_bindings={"artifact": object()},
                        ),
                    ),
                ),
                "invalid_binding",
            ),
            (
                replace(
                    base,
                    stages=(
                        base.stages[0],
                        replace(
                            base.stages[1],
                            evidence_bindings=(object(),),
                        ),
                    ),
                ),
                "invalid_evidence_binding",
            ),
            (
                replace(
                    base,
                    stages=(
                        base.stages[0],
                        replace(base.stages[1], authority=object()),
                    ),
                ),
                "invalid_authority_requirement",
            ),
        )

        for spec, reason_code in invalid_contracts:
            with self.subTest(reason_code=reason_code):
                with self.assertRaises(ContractFailure) as raised:
                    self.engine.run(spec)
                self.assertEqual(raised.exception.reason_code, reason_code)

        self.assertEqual(self.adapter.calls, [])
        self.assertFalse((self.root / "operations").exists())

    def test_mismatched_authority_declaration_is_rejected_before_claim(self) -> None:
        spec = self._spec()
        declaration = spec.authorities["release-authority"]
        spec = replace(
            spec,
            authorities={
                "release-authority": replace(
                    declaration,
                    logical_ref="different-authority",
                )
            },
        )

        with self.assertRaises(ContractFailure) as raised:
            self.engine.run(spec)

        self.assertEqual(
            raised.exception.reason_code,
            "authority_declaration_mismatch",
        )
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse((self.root / "operations").exists())

    def test_semantic_contract_invariants_are_recorded_before_adapter_calls(
        self,
    ) -> None:
        base = self._spec()
        prepare, release = base.stages
        evidence_binding = release.evidence_bindings[0]
        cases = (
            (
                replace(base, operation_id="invalid-kind", kind="Other"),
                "invalid_contract_kind",
            ),
            (
                replace(base, operation_id="empty-contract", stages=()),
                "empty_contract",
            ),
            (
                replace(
                    base,
                    operation_id="duplicate-stage",
                    stages=(prepare, prepare),
                ),
                "duplicate_stage",
            ),
            (
                replace(
                    base,
                    operation_id="duplicate-input",
                    stages=(prepare, replace(release, inputs={"artifact": "literal"})),
                ),
                "duplicate_input",
            ),
            (
                replace(
                    base,
                    operation_id="duplicate-evidence",
                    stages=(
                        prepare,
                        replace(
                            release,
                            evidence_bindings=(evidence_binding, evidence_binding),
                        ),
                    ),
                ),
                "duplicate_evidence_binding",
            ),
            (
                replace(
                    base,
                    operation_id="duplicate-dependency",
                    stages=(
                        prepare,
                        replace(release, requires=("prepare", "prepare")),
                    ),
                ),
                "duplicate_dependency",
            ),
            (
                replace(
                    base,
                    operation_id="missing-authority",
                    authorities={},
                ),
                "missing_authority_declaration",
            ),
            (
                replace(
                    base,
                    operation_id="unknown-binding",
                    stages=(
                        prepare,
                        replace(
                            release,
                            input_bindings={
                                "artifact": InputBinding(
                                    stage="missing",
                                    output="artifact",
                                )
                            },
                        ),
                    ),
                ),
                "unknown_binding",
            ),
            (
                replace(
                    base,
                    operation_id="unknown-evidence",
                    stages=(
                        prepare,
                        replace(
                            release,
                            evidence_bindings=(
                                EvidenceBinding(
                                    stage="missing",
                                    name="recovery-set",
                                    role="recovery_set",
                                ),
                            ),
                        ),
                    ),
                ),
                "unknown_evidence_binding",
            ),
            (
                replace(
                    base,
                    operation_id="unknown-adapter",
                    stages=(replace(prepare, adapter="missing"), release),
                ),
                "unknown_adapter",
            ),
            (
                replace(
                    base,
                    operation_id="unsupported-operation",
                    stages=(replace(prepare, operation="unsupported"), release),
                ),
                "unsupported_operation",
            ),
            (
                replace(
                    base,
                    operation_id="unsupported-recovery",
                    stages=(
                        replace(prepare, recovery_operation="unsupported"),
                        release,
                    ),
                ),
                "unsupported_recovery",
            ),
            (
                replace(
                    base,
                    operation_id="authority-capability",
                    stages=(
                        prepare,
                        replace(
                            release,
                            authority=AuthorityRequirement(
                                logical_ref="release-authority",
                                capability="different",
                            ),
                        ),
                    ),
                ),
                "authority_capability_mismatch",
            ),
            (
                replace(
                    base,
                    operation_id="authority-compatibility",
                    stages=(
                        prepare,
                        replace(
                            release,
                            authority=AuthorityRequirement(
                                logical_ref="release-authority",
                                capability="continuity",
                                compatibility=True,
                            ),
                        ),
                    ),
                ),
                "authority_compatibility_mismatch",
            ),
        )

        for spec, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                result = self.engine.run(spec)
                self.assertEqual(result.reason_code, reason_code)
                self.assertEqual(result.closure, "none")
                self.assertTrue(self._terminal_path(spec.operation_id).is_file())

        self.assertEqual(self.adapter.calls, [])

    def test_invalid_adapter_contracts_are_recorded_before_adapter_calls(
        self,
    ) -> None:
        invalid_identity = _Adapter()
        invalid_identity.identity = object()
        mismatched_identity = _Adapter()
        mismatched_identity.identity = replace(
            mismatched_identity.identity,
            name="token=private-adapter-identity",
        )
        unsupported_contract = _Adapter()
        unsupported_contract.identity = replace(
            unsupported_contract.identity,
            contract_version="token=private-adapter-version",
        )
        incomplete_identity = _Adapter()
        incomplete_identity.identity = replace(
            incomplete_identity.identity,
            distribution="",
        )
        invalid_operations = _Adapter()
        invalid_operations.operations = ("prepare",)
        cases = (
            ("invalid-adapter-identity", invalid_identity, "invalid_adapter_identity"),
            (
                "mismatched-adapter-identity",
                mismatched_identity,
                "adapter_identity_mismatch",
            ),
            (
                "unsupported-adapter-contract",
                unsupported_contract,
                "unsupported_adapter_contract",
            ),
            (
                "incomplete-adapter-identity",
                incomplete_identity,
                "invalid_adapter_identity",
            ),
            (
                "invalid-adapter-operations",
                invalid_operations,
                "invalid_adapter_contract",
            ),
        )

        for operation_id, adapter, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                result = self._engine(adapter=adapter).run(
                    replace(self._spec(), operation_id=operation_id)
                )
                self.assertEqual(result.reason_code, reason_code)
                self.assertEqual(result.closure, "none")
                self.assertEqual(adapter.calls, [])
                terminal = self._terminal_path(operation_id).read_text(encoding="utf-8")
                self.assertEqual(json.loads(terminal), result.to_evidence())
                self.assertNotIn("token=private-adapter", terminal)

    def test_cycle_is_rejected_before_adapter_calls(self) -> None:
        spec = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(
                StageSpec(
                    id="one",
                    adapter="local",
                    operation="prepare",
                    requires=("two",),
                ),
                StageSpec(
                    id="two",
                    adapter="local",
                    operation="release",
                    requires=("one",),
                ),
            ),
        )

        result = self.engine.run(spec)

        self.assertEqual(result.reason_code, "dependency_cycle")
        self.assertEqual(self.adapter.calls, [])

    def test_completed_operation_blocks_second_execution(self) -> None:
        self.engine.run(self._spec())
        calls = list(self.adapter.calls)

        with self.assertRaises(FileExistsError):
            self._engine().run(self._spec())

        self.assertEqual(self.adapter.calls, calls)
        self.assertTrue(self._terminal_path().is_file())

    def test_operation_claim_blocks_concurrent_mutation(self) -> None:
        self.adapter.execute_entered = threading.Event()
        self.adapter.execute_continue = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(self.engine.run, self._spec())
            self.assertTrue(self.adapter.execute_entered.wait(timeout=5))

            with self.assertRaises(FileExistsError):
                self._engine().run(self._spec())

            self.adapter.execute_continue.set()
            first.result(timeout=5)
        self.assertEqual(
            [call for call in self.adapter.calls if call[0] == "execute"],
            [("execute", "prepare"), ("execute", "release")],
        )
        self.assertTrue(self._terminal_path().is_file())

    def test_store_owns_distinct_terminal_path_for_each_operation(self) -> None:
        first = self._spec()
        second = replace(first, operation_id="test-run-two")

        self.engine.run(first)
        self.engine.run(second)

        self.assertEqual(
            [call for call in self.adapter.calls if call[0] == "execute"],
            [
                ("execute", "prepare"),
                ("execute", "release"),
                ("execute", "prepare"),
                ("execute", "release"),
            ],
        )
        first_path = self._terminal_path(first.operation_id)
        second_path = self._terminal_path(second.operation_id)
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())
        claims = list((self.root / "operations").glob("*/claim.json"))
        self.assertEqual(len(claims), 2)
        self.assertTrue(
            all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in claims)
        )

    def test_operation_store_rejects_mismatched_claim(self) -> None:
        store = FileOperationStore(self.root / "operations")

        with self.assertRaises(ValueError):
            store.acquire(
                "expected",
                {"operation_id": "different"},
            )

        self.assertFalse((self.root / "operations").exists())

    def test_operation_store_rejects_noncanonical_terminal_bytes(self) -> None:
        store = FileOperationStore(self.root / "operations")
        lease = store.acquire("probe-run", {"operation_id": "probe-run"})
        record = {"operation_id": "probe-run", "status": "succeeded"}
        store.publish(lease, record)
        lease.record_path.write_text(
            json.dumps(record, sort_keys=True),
            encoding="utf-8",
        )

        self.assertIs(store.probe(lease, record), PublicationState.CONFLICT)

    def test_absent_terminal_requires_a_visible_operation_claim(self) -> None:
        lease = self.store.acquire("run", {"operation_id": "run"})
        record = {"operation_id": "run", "status": "succeeded"}
        self.assertIs(self.store.probe(lease, record), PublicationState.ABSENT)

        claim = lease.record_path.with_name("claim.json")
        claim.rename(claim.with_name("archived-claim.json"))
        self.assertIs(self.store.probe(lease, record), PublicationState.UNKNOWN)

    def test_published_output_values_are_not_persisted(self) -> None:
        spec = self._spec()
        spec = replace(
            spec,
            stages=(
                replace(
                    spec.stages[0],
                    inputs={"source": "credential-material"},
                ),
                spec.stages[1],
            ),
        )
        record_path = self._terminal_path()

        result = self.engine.run(spec)

        terminal = record_path.read_text(encoding="utf-8")
        claim_path = next((self.root / "operations").glob("*/claim.json"))
        claim = claim_path.read_text(encoding="utf-8")
        claim_payload = json.loads(claim)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("admit", "release"),
                ("execute", "release"),
            ],
        )
        self.assertNotIn("credential-material", terminal)
        self.assertNotIn("artifact:credential-material", terminal)
        self.assertNotIn("credential-material", claim)
        self.assertNotIn("artifact:credential-material", claim)
        self.assertEqual(
            claim_payload["terminal_record"],
            str(record_path.resolve()),
        )

    def test_evidence_binding_requires_dependency_path(self) -> None:
        spec = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(
                StageSpec(
                    id="alpha",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "alpha"},
                    recovery_operation="remove",
                ),
                StageSpec(
                    id="release",
                    adapter="local",
                    operation="release",
                    inputs={"artifact": "literal"},
                    evidence_bindings=(
                        EvidenceBinding(
                            stage="alpha",
                            name="recovery-set",
                            role="recovery_set",
                        ),
                    ),
                ),
            ),
        )

        result = self.engine.run(spec)

        self.assertEqual(result.reason_code, "unordered_evidence_binding")
        self.assertEqual(self.adapter.calls, [])

    def test_input_binding_requires_ordered_published_output(self) -> None:
        prepare = StageSpec(
            id="prepare",
            adapter="local",
            operation="prepare",
            inputs={"source": "lab-a"},
            publish=frozenset({"artifact"}),
        )
        release = StageSpec(
            id="release",
            adapter="local",
            operation="release",
            input_bindings={
                "artifact": InputBinding(stage="prepare", output="artifact")
            },
        )
        cases = (
            (
                "unordered-binding",
                (prepare, release),
                "unordered_binding",
            ),
            (
                "unpublished-binding",
                (
                    replace(prepare, publish=frozenset()),
                    replace(release, requires=("prepare",)),
                ),
                "unpublished_binding",
            ),
        )

        for operation_id, stages, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                result = self.engine.run(
                    ContinuityContract(
                        operation_id=operation_id,
                        workload=self.workload,
                        stages=stages,
                    )
                )
                self.assertEqual(result.reason_code, reason_code)
                self.assertTrue(self._terminal_path(operation_id).is_file())

        self.assertEqual(self.adapter.calls, [])

    def test_evidence_store_failure_blocks_mutation(self) -> None:
        engine = self._engine(operation_store=_FailAcquireStore())

        with self.assertRaises(PermissionError):
            engine.run(self._spec())

        self.assertEqual(self.adapter.calls, [])

    def test_terminal_write_failure_recovers_before_second_publish(self) -> None:
        store = _FailOncePublishStore(self.root / "operations")
        engine = self._engine(operation_store=store)
        spec = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(
                StageSpec(
                    id="prepare",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "lab-a"},
                    publish=frozenset({"artifact"}),
                    recovery_operation="remove",
                ),
            ),
        )
        record_path = store.delegate.terminal_path(spec.operation_id)

        result = engine.run(spec)

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "terminal_record_write_failed")
        self.assertEqual(store.publish_attempts, 2)
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )
        self.assertTrue(record_path.is_file())

    def test_committed_terminal_survives_lost_acknowledgement(self) -> None:
        store = _WriteThenRaiseStore(self.root / "operations")
        engine = self._engine(operation_store=store)

        result = engine.run(self._spec())

        self.assertEqual(result.status, "succeeded")
        self.assertNotIn(("recover", "prepare"), self.adapter.calls)
        self.assertTrue(store.delegate.terminal_path("test-run").is_file())

    def test_lost_store_after_publication_does_not_trigger_compensation(self) -> None:
        spec = self._spec()
        spec = replace(spec, stages=(spec.stages[0],))
        store_root = self.root / "operations"
        moved_root = self.root / "moved-operations"
        publish = self.store.publish

        def publish_then_move(lease: OperationLease, record) -> None:
            publish(lease, record)
            store_root.rename(moved_root)
            self.store.acquire(spec.operation_id, {"operation_id": spec.operation_id})
            raise OSError("terminal acknowledgement unavailable")

        with (
            patch.object(self.store, "publish", side_effect=publish_then_move) as attempt,
            self.assertRaisesRegex(TerminalPersistenceError, "outcome is uncertain"),
        ):
            self.engine.run(spec)

        attempt.assert_called_once()
        lease, record = attempt.call_args.args
        self.assertIs(self.store.probe(lease, record), PublicationState.UNKNOWN)
        self.assertEqual(
            self.adapter.calls, [("admit", "prepare"), ("execute", "prepare")]
        )
        original = moved_root / lease.record_path.relative_to(store_root)
        self.assertEqual(json.loads(original.read_text(encoding="utf-8")), record)
        self.assertEqual(record["status"], "succeeded")
        self.assertFalse(lease.record_path.exists())
        self.assertTrue(lease.record_path.with_name("claim.json").is_file())

    def test_lost_claim_before_publication_does_not_trigger_compensation(self) -> None:
        spec = self._spec()
        spec = replace(spec, stages=(spec.stages[0],))
        publish = self.store.publish

        def lose_claim(lease: OperationLease, record) -> None:
            lease.record_path.with_name("claim.json").unlink()
            publish(lease, record)

        with (
            patch.object(self.store, "publish", side_effect=lose_claim) as attempt,
            self.assertRaisesRegex(TerminalPersistenceError, "outcome is uncertain"),
        ):
            self.engine.run(spec)

        attempt.assert_called_once()
        self.assertFalse(self._terminal_path(spec.operation_id).exists())
        self.assertEqual(
            self.adapter.calls, [("admit", "prepare"), ("execute", "prepare")]
        )

    def test_post_link_directory_sync_error_probes_committed_terminal(self) -> None:
        real_sync = continuity_storage._sync_directory
        terminal_path = self._terminal_path()
        terminal_syncs = 0

        def fail_terminal_sync_once(path: Path, directory: int | None = None) -> None:
            nonlocal terminal_syncs
            if path == terminal_path.parent and terminal_path.is_file():
                terminal_syncs += 1
                if terminal_syncs == 1:
                    raise OSError("terminal directory sync failed")
            real_sync(path, directory)

        with patch.object(
            continuity_storage,
            "_sync_directory",
            side_effect=fail_terminal_sync_once,
        ):
            result = self.engine.run(self._spec())

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(terminal_syncs, 2)
        self.assertNotIn(("recover", "prepare"), self.adapter.calls)
        self.assertTrue(self._terminal_path().is_file())

    def test_unknown_terminal_outcome_preserves_recovery_material(self) -> None:
        store = _UnknownPublishStore(self.root / "operations")
        engine = self._engine(operation_store=store)

        with self.assertRaisesRegex(
            TerminalPersistenceError,
            "outcome is uncertain",
        ):
            engine.run(self._spec())

        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("admit", "release"),
                ("execute", "release"),
            ],
        )

    def test_conflicting_terminal_outcome_preserves_recovery_material(self) -> None:
        store = _ConflictPublishStore(self.root / "operations")
        engine = self._engine(operation_store=store)

        with self.assertRaisesRegex(
            TerminalPersistenceError,
            "conflicts with the stored record",
        ):
            engine.run(self._spec())

        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("admit", "release"),
                ("execute", "release"),
            ],
        )

    def test_undeclared_later_recovery_blocks_recovery_set_removal(self) -> None:
        store = _FailOncePublishStore(self.root / "operations")
        engine = self._engine(operation_store=store)

        result = engine.run(self._spec())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.closure, "recovery_failed")
        self.assertEqual(result.stages[1].recovery_status, "not_declared")
        self.assertEqual(result.stages[0].recovery_status, "blocked")
        self.assertEqual(
            result.stages[0].recovery_reason_code,
            "blocked_by_later_recovery",
        )
        self.assertNotIn(("recover", "prepare"), self.adapter.calls)

    def test_failed_later_recovery_blocks_recovery_set_removal(self) -> None:
        store = _FailOncePublishStore(self.root / "operations")
        engine = self._engine(operation_store=store)
        self.adapter.recovery_succeeds = False
        spec = self._spec()
        spec = replace(
            spec,
            stages=(
                spec.stages[0],
                replace(spec.stages[1], recovery_operation="remove"),
            ),
        )

        result = engine.run(spec)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.closure, "recovery_failed")
        self.assertEqual(result.stages[1].recovery_status, "failed")
        self.assertEqual(result.stages[0].recovery_status, "blocked")
        self.assertEqual(
            result.stages[0].recovery_reason_code,
            "blocked_by_later_recovery",
        )
        self.assertEqual(self.adapter.calls[-1], ("recover", "release"))
        self.assertNotIn(("recover", "prepare"), self.adapter.calls)

    def test_lexical_order_is_stable_for_independent_stages(self) -> None:
        spec = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(
                StageSpec(
                    id="zeta",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "zeta"},
                ),
                StageSpec(
                    id="alpha",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "alpha"},
                ),
            ),
        )

        self.engine.run(spec)

        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "alpha"),
                ("execute", "alpha"),
                ("admit", "zeta"),
                ("execute", "zeta"),
            ],
        )

    def test_authority_denial_recovers_prior_mutation(self) -> None:
        spec = self._spec()
        declaration = spec.authorities["release-authority"]
        spec = replace(
            spec,
            authorities={
                "release-authority": replace(
                    declaration,
                    config={"ready": False},
                )
            },
        )

        result = self.engine.run(spec)

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "authority_denied")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )

    def test_malformed_authority_health_denies_before_adapter_dispatch(self) -> None:
        spec = self._spec()
        prepare, release = spec.stages
        spec = replace(spec, stages=(replace(prepare, authority=release.authority),))
        malformed = AuthorityEvaluation(
            healthy="false",
            state="ready",
            result="private-provider-detail",
        )
        with patch.object(_AuthorityProvider, "evaluate", return_value=malformed):
            result = self.engine.run(spec)

        self.assertEqual(result.reason_code, "authority_denied")
        self.assertEqual(result.closure, "none")
        self.assertEqual(self.adapter.calls, [])
        terminal = self._terminal_path().read_text(encoding="utf-8")
        self.assertEqual(json.loads(terminal), result.to_evidence())
        self.assertNotIn("private-provider-detail", terminal)

    def test_authority_provider_error_is_stable_and_terminal(self) -> None:
        spec = self._spec()
        declaration = spec.authorities["release-authority"]
        spec = replace(
            spec,
            authorities={
                "release-authority": replace(
                    declaration,
                    config={"ready": True, "error": True},
                )
            },
        )

        result = self.engine.run(spec)

        self.assertEqual(result.reason_code, "authority_error")
        self.assertEqual(
            result.result,
            "stage 'release' authority evaluation failed",
        )
        self.assertNotIn("provider detail", result.result)

    def test_authority_receipt_must_match_declared_provider(self) -> None:
        receipt = AuthorityReceipt(
            logical_ref="release-authority",
            capability="continuity",
            provider="different-provider",
            provider_identity=AuthorityProviderIdentity(
                source="direct",
                distribution="different-provider",
                version="1.0.0",
                entry_point="tests:_ReceiptGate",
            ),
            state="ready",
            result="provider-secret",
        )
        engine = self._engine(authority_gate=_ReceiptGate(receipt))

        result = engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "invalid_authority_receipt")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )
        self.assertNotIn(
            "provider-secret",
            self._terminal_path().read_text(encoding="utf-8"),
        )

    def test_authority_receipt_requires_valid_provider_provenance(self) -> None:
        receipt = AuthorityReceipt(
            logical_ref="release-authority",
            capability="continuity",
            provider="local",
            provider_identity=AuthorityProviderIdentity(
                source="direct",
                distribution="hybridops-conformance",
                version="1.0.0",
                entry_point="tests:_ReceiptGate",
                contract_version="2",
            ),
            state="ready",
            result="provider-secret",
        )
        engine = self._engine(authority_gate=_ReceiptGate(receipt))

        result = engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "invalid_authority_receipt")
        self.assertNotIn(
            "provider-secret",
            self._terminal_path().read_text(encoding="utf-8"),
        )

    def test_missing_published_output_recovers_mutated_stage(self) -> None:
        self.adapter.omit_prepare_output = True

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "missing_published_output")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )
        self.assertEqual(result.stages[0].status, "failed")
        self.assertEqual(result.stages[0].recovery_status, "succeeded")
        self.assertEqual(
            self.adapter.recovery_outputs["prepare"],
            {"private": "not-published"},
        )

    def test_single_stage_requires_its_declared_evidence(self) -> None:
        base = self._spec()
        snapshot = EvidenceIdentity("snapshot", "recovery_set", "sha256:" + "a" * 64)
        config = EvidenceIdentity("config", "configuration", "sha256:" + "b" * 64)
        required = {item.name: item.role for item in (snapshot, config)}
        missing = "missing_producer_evidence"
        cases = (
            ("absent", required, (), missing),
            ("partial", required, (config,), missing),
            (
                "wrong-name",
                required,
                (config, replace(snapshot, name="other")),
                missing,
            ),
            (
                "wrong-role",
                required,
                (config, replace(snapshot, role="report")),
                missing,
            ),
            (
                "bad-digest",
                required,
                (config, replace(snapshot, digest="bad")),
                "invalid_evidence_identity",
            ),
            ("complete", required, (config, snapshot), ""),
            ("optional", {}, (), ""),
        )
        for case, declared, returned, reason in cases:
            with self.subTest(case=case):
                producer = replace(base.stages[0], produced_evidence=declared)
                self.adapter.omit_prepare_evidence = not returned
                self.adapter.prepare_evidence_override = returned
                result = self.engine.run(
                    replace(base, operation_id=case, stages=(producer,))
                )
                self.assertEqual(result.reason_code, reason)
                self.assertEqual(result.status, "recovered" if reason else "succeeded")
                (stage,) = result.stages
                self.assertEqual(stage.status, "failed" if reason else "succeeded")
                self.assertEqual(stage.evidence, () if reason else returned)
                self.assertEqual(stage.reason_code, reason)
                self.assertEqual(
                    json.loads(self._terminal_path(case).read_text())["stages"],
                    [stage.to_evidence()],
                )

    def test_missing_producer_evidence_stops_successor_without_consumer_binding(
        self,
    ) -> None:
        spec = self._spec()
        producer = replace(
            spec.stages[0], produced_evidence={"recovery-set": "recovery_set"}
        )
        successor = replace(spec.stages[1], evidence_bindings=())
        self.adapter.omit_prepare_evidence = True

        result = self.engine.run(replace(spec, stages=(producer, successor)))

        self.assertEqual(result.reason_code, "missing_producer_evidence")
        self.assertEqual(
            self.adapter.calls,
            [("admit", "prepare"), ("execute", "prepare"), ("recover", "prepare")],
        )

    def test_release_requires_content_identified_recovery_evidence(self) -> None:
        self.adapter.omit_prepare_evidence = True

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "missing_required_evidence")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )

    def test_release_requires_exact_evidence_identity(self) -> None:
        spec = self._spec()
        spec = replace(
            spec,
            stages=(
                spec.stages[0],
                replace(
                    spec.stages[1],
                    evidence_bindings=(
                        EvidenceBinding(
                            stage="prepare",
                            name="different-set",
                            role="recovery_set",
                        ),
                    ),
                ),
            ),
        )

        result = self.engine.run(spec)

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "missing_required_evidence")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )

    def test_evidence_identity_is_exact_and_content_addressed(self) -> None:
        valid_digest = "sha256:" + "b" * 64
        cases = (
            (
                "wrong-evidence-role",
                (
                    EvidenceIdentity(
                        name="recovery-set",
                        role="other_role",
                        digest=valid_digest,
                    ),
                ),
                "missing_required_evidence",
            ),
            (
                "malformed-evidence-digest",
                (
                    EvidenceIdentity(
                        name="recovery-set",
                        role="recovery_set",
                        digest="invalid",
                    ),
                ),
                "invalid_evidence_identity",
            ),
            (
                "duplicate-evidence-identity",
                (
                    EvidenceIdentity(
                        name="recovery-set",
                        role="recovery_set",
                        digest=valid_digest,
                    ),
                    EvidenceIdentity(
                        name="recovery-set",
                        role="other_role",
                        digest=valid_digest,
                    ),
                ),
                "duplicate_evidence_identity",
            ),
        )

        for operation_id, evidence, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                self.adapter.prepare_evidence_override = evidence
                result = self.engine.run(
                    replace(self._spec(), operation_id=operation_id)
                )
                self.assertEqual(result.reason_code, reason_code)
                self.assertEqual(result.closure, "recovered")
                self.assertEqual(self.adapter.calls[-1], ("recover", "prepare"))
                self.adapter.calls.clear()

    def test_admission_boundary_failures_are_stable_and_terminal(self) -> None:
        def raise_admission_error(_request):
            raise RuntimeError("admission detail must not escape")

        cases = (
            (
                "admission-error",
                raise_admission_error,
                "adapter_admission_error",
            ),
            (
                "invalid-admission-result",
                lambda _request: object(),
                "invalid_admission_result",
            ),
            (
                "invalid-admission-decision",
                lambda _request: AdmissionResult(allowed="yes"),
                "invalid_admission_result",
            ),
            (
                "invalid-admission-reason",
                lambda _request: AdmissionResult(
                    allowed=True,
                    reason_code="invalid reason",
                ),
                "invalid_admission_result",
            ),
        )

        for operation_id, handler, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                with patch.object(self.adapter, "admit", side_effect=handler):
                    result = self.engine.run(
                        replace(self._spec(), operation_id=operation_id)
                    )
                self.assertEqual(result.reason_code, reason_code)
                self.assertEqual(result.closure, "none")
                self.assertNotIn("admission detail", result.result)

    def test_execution_boundary_failures_attempt_recovery(self) -> None:
        def invalid_outputs(_request):
            result = ExecutionResult()
            object.__setattr__(result, "outputs", object())
            return result

        def invalid_evidence(_request):
            result = ExecutionResult(outputs={"artifact": "artifact:test"})
            object.__setattr__(result, "evidence", object())
            return result

        cases = (
            (
                "invalid-execution-result",
                lambda _request: object(),
                "invalid_execution_result",
            ),
            (
                "invalid-stage-outputs",
                invalid_outputs,
                "invalid_stage_outputs",
            ),
            (
                "invalid-stage-evidence",
                invalid_evidence,
                "invalid_evidence_identity",
            ),
        )

        for operation_id, handler, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                with patch.object(self.adapter, "execute", side_effect=handler):
                    result = self.engine.run(
                        replace(self._spec(), operation_id=operation_id)
                    )
                self.assertEqual(result.reason_code, reason_code)
                self.assertEqual(result.closure, "recovered")
                self.assertEqual(result.stages[0].recovery_status, "succeeded")
                self.adapter.calls.clear()

    def test_recovery_boundary_failures_are_stable_and_terminal(self) -> None:
        def raise_recovery_error(_request):
            raise RuntimeError("recovery detail must not escape")

        cases = (
            (
                "recovery-error",
                raise_recovery_error,
                "adapter_recovery_error",
            ),
            (
                "invalid-recovery-result",
                lambda _request: object(),
                "invalid_recovery_result",
            ),
            (
                "invalid-recovery-decision",
                lambda _request: RecoveryResult(succeeded="yes"),
                "invalid_recovery_result",
            ),
            (
                "invalid-recovery-reason",
                lambda _request: RecoveryResult(
                    succeeded=True,
                    reason_code="invalid reason",
                ),
                "invalid_recovery_result",
            ),
        )
        self.adapter.denied_operations.add("release")

        for operation_id, handler, adapter_reason_code in cases:
            with self.subTest(adapter_reason_code=adapter_reason_code):
                with patch.object(self.adapter, "recover", side_effect=handler):
                    result = self.engine.run(
                        replace(self._spec(), operation_id=operation_id)
                    )
                self.assertEqual(result.closure, "recovery_failed")
                self.assertEqual(
                    result.stages[0].adapter_recovery_reason_code,
                    adapter_reason_code,
                )
                self.assertNotIn("recovery detail", result.result)
                self.adapter.calls.clear()

    def test_execution_error_attempts_declared_recovery(self) -> None:
        self.adapter.execute_errors.add("prepare")

        result = self.engine.run(self._spec())

        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.reason_code, "adapter_execution_error")
        self.assertEqual(
            self.adapter.calls,
            [
                ("admit", "prepare"),
                ("execute", "prepare"),
                ("recover", "prepare"),
            ],
        )
        self.assertNotIn("adapter detail", result.result)

    def test_recovery_runs_in_reverse_execution_order(self) -> None:
        self.adapter.denied_operations.add("release")
        spec = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(
                StageSpec(
                    id="alpha",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "alpha"},
                    publish=frozenset({"artifact"}),
                    recovery_operation="remove",
                ),
                StageSpec(
                    id="beta",
                    adapter="local",
                    operation="prepare",
                    inputs={"source": "beta"},
                    publish=frozenset({"artifact"}),
                    recovery_operation="remove",
                ),
                StageSpec(
                    id="release",
                    adapter="local",
                    operation="release",
                    requires=("alpha", "beta"),
                    input_bindings={
                        "artifact": InputBinding(stage="beta", output="artifact")
                    },
                ),
            ),
        )

        result = self.engine.run(spec)

        self.assertEqual(result.status, "recovered")
        self.assertEqual(
            self.adapter.calls[-2:],
            [("recover", "beta"), ("recover", "alpha")],
        )

    def test_unsupported_contract_version_is_terminal(self) -> None:
        spec = replace(self._spec(), schema_version="2")

        result = self.engine.run(spec)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason_code, "unsupported_contract_version")
        self.assertEqual(self.adapter.calls, [])

    def test_contract_deeply_copies_mutable_collections(self) -> None:
        inputs = {"source": {"name": "original", "members": ["one"]}}
        authorities = {
            "release-authority": AuthorityDeclaration(
                logical_ref="release-authority",
                capability="continuity",
                provider="local",
                config={"scope": {"name": "original"}},
            )
        }
        stage = StageSpec(
            id="prepare",
            adapter="local",
            operation="prepare",
            inputs=inputs,
        )
        contract = ContinuityContract(
            operation_id="test-run",
            workload=self.workload,
            stages=(stage,),
            authorities=authorities,
        )

        inputs["source"]["name"] = "changed"
        inputs["source"]["members"].append("two")
        authorities["release-authority"].config["scope"]["name"] = "changed"
        authorities["unexpected"] = object()

        self.assertEqual(contract.stages[0].inputs["source"]["name"], "original")
        self.assertEqual(contract.stages[0].inputs["source"]["members"], ("one",))
        self.assertEqual(
            contract.authorities["release-authority"].config["scope"]["name"],
            "original",
        )
        self.assertNotIn("unexpected", contract.authorities)
        with self.assertRaises(TypeError):
            contract.stages[0].inputs["source"]["name"] = "blocked"

    def test_contract_requires_canonical_container_types(self) -> None:
        stage = StageSpec(
            id="prepare",
            adapter="local",
            operation="prepare",
        )

        with self.assertRaisesRegex(TypeError, "stages must be a tuple"):
            ContinuityContract(
                operation_id="test-run",
                workload=self.workload,
                stages=[stage],
            )
        with self.assertRaisesRegex(TypeError, "dependencies must be a tuple"):
            StageSpec(
                id="prepare",
                adapter="local",
                operation="prepare",
                requires=["earlier"],
            )
        with self.assertRaisesRegex(TypeError, "published outputs"):
            StageSpec(
                id="prepare",
                adapter="local",
                operation="prepare",
                publish={"artifact"},
            )
        with self.assertRaisesRegex(TypeError, "evidence bindings"):
            StageSpec(
                id="prepare",
                adapter="local",
                operation="prepare",
                evidence_bindings=[],
            )

        with self.assertRaises(TypeError):
            replace(stage, produced_evidence=[])

    def test_producer_declaration_is_immutable_and_part_of_the_digest(self) -> None:
        spec = self._spec()
        declarations = {"snapshot": "recovery_set", "config": "configuration"}

        def with_declarations(items):
            return replace(
                spec,
                stages=(
                    replace(spec.stages[0], produced_evidence=items),
                    spec.stages[1],
                ),
            )

        contract = with_declarations(declarations)
        digest = contract.digest()
        self.assertEqual(
            digest, with_declarations(dict(reversed(declarations.items()))).digest()
        )
        self.assertNotEqual(digest, spec.digest())
        self.assertNotEqual(
            digest, with_declarations({**declarations, "config": "report"}).digest()
        )
        declarations.clear()
        self.assertEqual(contract.digest(), digest)
        with self.assertRaises(TypeError):
            contract.stages[0].produced_evidence["config"] = "report"

    def test_contract_digest_is_canonical_and_materially_sensitive(self) -> None:
        first = self._spec()
        self.assertEqual(
            first.digest(),
            "sha256:2e3192c6c64fb87153e2f44f88c59c445dde3608a5f8d79c138ebc3ef135ba40",
        )
        declaration = first.authorities["release-authority"]
        reordered = replace(
            first,
            authorities={
                "release-authority": replace(
                    declaration,
                    config={"zeta": 2, "ready": True, "alpha": 1},
                )
            },
        )
        same_reordered = replace(
            first,
            authorities={
                "release-authority": replace(
                    declaration,
                    config={"alpha": 1, "ready": True, "zeta": 2},
                )
            },
        )
        changed = replace(
            same_reordered,
            workload=replace(first.workload, revision="different-revision"),
        )

        self.assertEqual(reordered.digest(), same_reordered.digest())
        self.assertNotEqual(same_reordered.digest(), changed.digest())


if __name__ == "__main__":
    unittest.main()
