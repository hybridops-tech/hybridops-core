"""Deterministic continuity contract execution."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from hyops.authority.models import (
    AUTHORITY_PROVIDER_CONTRACT_VERSION,
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityObservation,
    AuthorityReceipt,
)

from .adapter import AuthorityGate, ContinuityAdapter
from .errors import ContractFailure, TerminalPersistenceError
from .evidence import RetainedEvidenceReader, verify_retained
from .models import (
    CONTROLLER_CONTRACT_VERSION,
    AdapterRequest,
    AdmissionResult,
    AuthorityAdmission,
    AuthorityProviderProvenance,
    ContinuityContract,
    ControllerIdentity,
    EvidenceBinding,
    EvidenceIdentity,
    ExecutionResult,
    OutputIdentity,
    RecoveryRequest,
    RecoveryResult,
    StageRecord,
    StageSpec,
    TerminalRecord,
    json_digest,
)
from .storage import OperationLease, OperationStore, PublicationState
from .validation import (
    AdapterCapabilities,
    is_sha256_digest,
    is_token,
    validate_contract_semantics,
    validate_contract_shape,
)


class ContinuityEngine:
    """Execute a continuity contract through injected adapters and authority."""

    def __init__(
        self,
        *,
        adapters: Mapping[str, ContinuityAdapter],
        authority_gate: AuthorityGate,
        authority_context: AuthorityContext,
        controller_identity: ControllerIdentity,
        operation_store: OperationStore,
        clock: Callable[[], datetime] | None = None,
        evidence_reader: RetainedEvidenceReader | None = None,
        evidence_timeout_seconds: float = 3600,
    ) -> None:
        self._validate_controller_identity(controller_identity)
        self._adapters = dict(adapters)
        self._authority_gate = authority_gate
        self._authority_context = authority_context
        self._controller_identity = controller_identity
        self._operation_store = operation_store
        if (
            type(evidence_timeout_seconds) not in (float, int)
            or not math.isfinite(evidence_timeout_seconds)
            or evidence_timeout_seconds <= 0
        ):
            raise ValueError("retained evidence timeout must be finite and positive")
        self._evidence_reader = evidence_reader
        self._evidence_timeout = evidence_timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _validate_controller_identity(identity: ControllerIdentity) -> None:
        if not isinstance(identity, ControllerIdentity):
            raise TypeError("controller identity has an invalid type")
        for field_name in ("distribution", "version", "revision"):
            value = getattr(identity, field_name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(f"controller identity has invalid {field_name}")
        if identity.contract_version != CONTROLLER_CONTRACT_VERSION:
            raise ValueError("controller identity has unsupported contract version")

    def run(self, spec: ContinuityContract) -> TerminalRecord:
        validate_contract_shape(spec)
        started_at = self._timestamp()
        contract_digest = spec.digest()
        lease = self._operation_store.acquire(
            spec.operation_id,
            self._claim(spec, contract_digest, started_at),
        )
        records: list[StageRecord] = []
        completed: list[tuple[StageSpec, RecoveryRequest | None]] = []
        outputs: dict[str, Mapping[str, Any]] = {}
        evidence_by_stage: dict[str, tuple[EvidenceIdentity, ...]] = {}
        current_stage: StageSpec | None = None
        current_authority: AuthorityAdmission | None = None
        adapter_contracts: Mapping[str, AdapterCapabilities] = {}

        try:
            order, adapter_contracts = validate_contract_semantics(
                spec,
                self._adapters,
            )
            by_id = {stage.id: stage for stage in spec.stages}
            if self._evidence_reader is None and any(
                stage.destructive for stage in spec.stages
            ):
                raise ContractFailure(
                    "retained_evidence_unavailable",
                    "destructive stages require a retained evidence reader",
                )
            for stage_id in order:
                stage = by_id[stage_id]
                current_stage = stage
                current_authority = None
                adapter = self._adapters[stage.adapter]
                inputs = self._resolve_inputs(stage, outputs)
                required = self._require_evidence(stage, evidence_by_stage)
                authority_receipt, authority = self._enforce_authority(spec, stage)
                current_authority = authority
                subject = (
                    self._authority_subject(authority_receipt)
                    if stage.destructive
                    else None
                )
                request = AdapterRequest(
                    operation_id=spec.operation_id,
                    stage_id=stage.id,
                    operation=stage.operation,
                    inputs=inputs,
                    authority_receipt=authority_receipt,
                )
                admission = self._admit(adapter, request)
                if not admission.allowed:
                    denial_result = f"stage '{stage.id}' admission denied"
                    records.append(
                        self._stage_record(
                            stage,
                            capabilities=adapter_contracts[stage.adapter],
                            status="denied",
                            reason_code="adapter_admission_denied",
                            adapter_reason_code=admission.reason_code,
                            result=denial_result,
                            authority=authority,
                        )
                    )
                    raise ContractFailure(
                        "adapter_admission_denied",
                        denial_result,
                    )

                if stage.destructive:
                    verify_retained(
                        self._evidence_reader,
                        spec.operation_id,
                        spec.workload,
                        required,
                        self._evidence_timeout,
                    )
                    current_authority = None
                    refreshed, refreshed_admission = self._enforce_authority(
                        spec, stage
                    )
                    if (
                        refreshed_admission != authority
                        or self._authority_subject(refreshed) != subject
                    ):
                        raise ContractFailure(
                            "authority_changed",
                            f"authority changed before stage '{stage.id}' dispatch",
                        )
                    current_authority = refreshed_admission
                    request = AdapterRequest(
                        spec.operation_id, stage.id, stage.operation, inputs, refreshed
                    )
                try:
                    execution = self._execute(adapter, request)
                except ContractFailure:
                    completed.append(
                        (stage, self._recovery_request(spec, stage, inputs, {}))
                    )
                    raise
                try:
                    stage_outputs = self._snapshot_outputs(stage, execution)
                except ContractFailure:
                    completed.append(
                        (stage, self._recovery_request(spec, stage, inputs, {}))
                    )
                    raise
                completed.append(
                    (
                        stage,
                        self._recovery_request(
                            spec,
                            stage,
                            inputs,
                            stage_outputs,
                        ),
                    )
                )
                self._validate_outputs(stage, stage_outputs)
                stage_evidence = self._validate_evidence(stage, execution)
                evidence_by_stage[stage.id] = stage_evidence
                outputs[stage.id] = stage_outputs
                records.append(
                    self._stage_record(
                        stage,
                        capabilities=adapter_contracts[stage.adapter],
                        status="succeeded",
                        result="stage operation completed",
                        authority=authority,
                        outputs=stage_outputs,
                        evidence=stage_evidence,
                    )
                )
                current_stage = None
                current_authority = None
        except ContractFailure as exc:
            if current_stage is not None and all(
                record.stage_id != current_stage.id for record in records
            ):
                records.append(
                    self._stage_record(
                        current_stage,
                        capabilities=adapter_contracts[current_stage.adapter],
                        status="failed",
                        reason_code=exc.reason_code,
                        result=exc.result,
                        authority=current_authority,
                    )
                )
            recovery_failed = self._recover(completed, records, adapter_contracts)
            if recovery_failed:
                status = "failed"
                closure = "recovery_failed"
            elif completed:
                status = "recovered"
                closure = "recovered"
            else:
                status = "failed"
                closure = "none"
            terminal = self._terminal(
                spec,
                contract_digest=contract_digest,
                status=status,
                closure=closure,
                reason_code=exc.reason_code,
                result=exc.result,
                started_at=started_at,
                records=records,
            )
            publication_state, publish_error = self._publish_terminal(
                lease,
                terminal,
            )
            if (
                publish_error is not None
                and publication_state is not PublicationState.COMMITTED
            ):
                raise TerminalPersistenceError(
                    "terminal evidence publication failed"
                ) from publish_error
            return terminal

        terminal = self._terminal(
            spec,
            contract_digest=contract_digest,
            status="succeeded",
            closure="completed",
            reason_code="",
            result="continuity operation completed",
            started_at=started_at,
            records=records,
        )
        publication_state, publish_error = self._publish_terminal(lease, terminal)
        if publish_error is None or publication_state is PublicationState.COMMITTED:
            return terminal
        if publication_state is PublicationState.CONFLICT:
            raise TerminalPersistenceError(
                "terminal evidence conflicts with the stored record"
            ) from publish_error
        if publication_state is PublicationState.UNKNOWN:
            raise TerminalPersistenceError(
                "terminal evidence publication outcome is uncertain"
            ) from publish_error
        recovery_failed = self._recover(completed, records, adapter_contracts)
        terminal = self._terminal(
            spec,
            contract_digest=contract_digest,
            status="failed" if recovery_failed else "recovered",
            closure="recovery_failed" if recovery_failed else "recovered",
            reason_code="terminal_record_write_failed",
            result="terminal evidence publication failed",
            started_at=started_at,
            records=records,
        )
        final_state, final_error = self._publish_terminal(lease, terminal)
        if final_error is not None and final_state is not PublicationState.COMMITTED:
            raise TerminalPersistenceError(
                "terminal evidence publication failed after recovery"
            ) from final_error
        return terminal

    def _resolve_inputs(
        self,
        stage: StageSpec,
        outputs: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        resolved = dict(stage.inputs)
        for name, binding in stage.input_bindings.items():
            resolved[name] = outputs[binding.stage][binding.output]
        return resolved

    @staticmethod
    def _authority_subject(receipt: AuthorityReceipt | None) -> tuple[str, ...]:
        if receipt is not None:
            fields = (receipt.instance, receipt.endpoint, receipt.revision)
            observation = receipt.observation
            if isinstance(observation, AuthorityObservation):
                fields += (observation.scope, observation.token, observation.strength)
            if (
                observation is None or isinstance(observation, AuthorityObservation)
            ) and all(type(value) is str for value in fields):
                return fields
        raise ContractFailure(
            "invalid_authority_receipt", "invalid retirement authority identity"
        )

    def _enforce_authority(
        self,
        spec: ContinuityContract,
        stage: StageSpec,
    ) -> tuple[AuthorityReceipt | None, AuthorityAdmission | None]:
        if stage.authority is None:
            return None, None
        try:
            receipt = self._authority_gate.enforce(
                stage.authority,
                spec.authorities,
                self._authority_context,
            )
        except (TypeError, ValueError) as exc:
            raise ContractFailure(
                "authority_denied",
                f"stage '{stage.id}' authority admission denied",
            ) from exc
        except Exception as exc:
            raise ContractFailure(
                "authority_error",
                f"stage '{stage.id}' authority evaluation failed",
            ) from exc
        admission = self._validate_authority_receipt(spec, stage, receipt)
        return receipt, admission

    @staticmethod
    def _validate_authority_receipt(
        spec: ContinuityContract,
        stage: StageSpec,
        receipt: AuthorityReceipt,
    ) -> AuthorityAdmission:
        requirement = stage.authority
        declaration = (
            spec.authorities.get(requirement.logical_ref)
            if requirement is not None
            else None
        )
        if requirement is None or not isinstance(receipt, AuthorityReceipt):
            raise ContractFailure(
                "invalid_authority_receipt",
                f"stage '{stage.id}' returned an invalid authority receipt",
            )
        try:
            admission = ContinuityEngine._authority_evidence(receipt)
        except Exception as exc:
            raise ContractFailure(
                "invalid_authority_receipt",
                f"stage '{stage.id}' returned an invalid authority receipt",
            ) from exc
        if (
            not isinstance(declaration, AuthorityDeclaration)
            or declaration.logical_ref != requirement.logical_ref
            or admission.logical_ref != requirement.logical_ref
            or admission.capability != requirement.capability
            or admission.provider != declaration.provider
            or not is_token(admission.logical_ref)
            or not is_token(admission.capability)
            or not is_token(admission.provider)
            or not ContinuityEngine._valid_authority_provider_provenance(
                admission.provider_identity
            )
        ):
            raise ContractFailure(
                "invalid_authority_receipt",
                f"stage '{stage.id}' returned an invalid authority receipt",
            )
        return admission

    @staticmethod
    def _valid_authority_provider_provenance(
        identity: AuthorityProviderProvenance,
    ) -> bool:
        if not isinstance(identity, AuthorityProviderProvenance):
            return False
        if identity.contract_version != AUTHORITY_PROVIDER_CONTRACT_VERSION:
            return False
        return all(
            isinstance(value, str) and bool(value.strip()) and value == value.strip()
            for value in (
                identity.source,
                identity.distribution,
                identity.version,
                identity.entry_point,
            )
        )

    def _probe_publication(
        self,
        lease: OperationLease,
        terminal: TerminalRecord,
    ) -> PublicationState:
        try:
            state = self._operation_store.probe(lease, terminal.to_evidence())
        except Exception:  # noqa: BLE001 - operation-store boundary
            return PublicationState.UNKNOWN
        if not isinstance(state, PublicationState):
            return PublicationState.UNKNOWN
        return state

    @staticmethod
    def _admit(
        adapter: ContinuityAdapter,
        request: AdapterRequest,
    ) -> AdmissionResult:
        try:
            result = adapter.admit(request)
        except Exception as exc:
            raise ContractFailure(
                "adapter_admission_error",
                f"stage '{request.stage_id}' admission failed",
            ) from exc
        if not isinstance(result, AdmissionResult):
            raise ContractFailure(
                "invalid_admission_result",
                f"stage '{request.stage_id}' returned an invalid admission result",
            )
        if type(result.allowed) is not bool:
            raise ContractFailure(
                "invalid_admission_result",
                f"stage '{request.stage_id}' returned an invalid admission decision",
            )
        ContinuityEngine._validate_reason_code(
            request.stage_id,
            result.reason_code,
            "admission",
        )
        return result

    @staticmethod
    def _execute(
        adapter: ContinuityAdapter,
        request: AdapterRequest,
    ) -> ExecutionResult:
        try:
            result = adapter.execute(request)
        except Exception as exc:
            raise ContractFailure(
                "adapter_execution_error",
                f"stage '{request.stage_id}' execution failed",
            ) from exc
        if not isinstance(result, ExecutionResult):
            raise ContractFailure(
                "invalid_execution_result",
                f"stage '{request.stage_id}' returned an invalid execution result",
            )
        return result

    @staticmethod
    def _snapshot_outputs(
        stage: StageSpec,
        execution: ExecutionResult,
    ) -> Mapping[str, Any]:
        try:
            outputs = execution.outputs
        except Exception as exc:
            raise ContractFailure(
                "invalid_stage_outputs",
                f"stage '{stage.id}' returned invalid outputs",
            ) from exc
        if not isinstance(outputs, Mapping):
            raise ContractFailure(
                "invalid_stage_outputs",
                f"stage '{stage.id}' returned invalid outputs",
            )
        try:
            snapshot = ExecutionResult(outputs=outputs).outputs
        except Exception as exc:
            raise ContractFailure(
                "invalid_stage_outputs",
                f"stage '{stage.id}' returned invalid outputs",
            ) from exc
        return snapshot

    @staticmethod
    def _validate_outputs(stage: StageSpec, outputs: Mapping[str, Any]) -> None:
        missing = sorted(stage.publish - set(outputs))
        if missing:
            raise ContractFailure(
                "missing_published_output",
                f"stage '{stage.id}' did not return published output(s): "
                f"{', '.join(missing)}",
            )

    @staticmethod
    def _validate_evidence(
        stage: StageSpec,
        execution: ExecutionResult,
    ) -> tuple[EvidenceIdentity, ...]:
        try:
            evidence = execution.evidence
        except Exception as exc:
            raise ContractFailure(
                "invalid_evidence_identity",
                f"stage '{stage.id}' returned invalid evidence",
            ) from exc
        if not isinstance(evidence, tuple):
            raise ContractFailure(
                "invalid_evidence_identity",
                f"stage '{stage.id}' returned invalid evidence",
            )
        try:
            identities = tuple(iter(evidence))
        except Exception as exc:
            raise ContractFailure(
                "invalid_evidence_identity",
                f"stage '{stage.id}' returned invalid evidence",
            ) from exc
        validated: dict[str, EvidenceIdentity] = {}
        for item in identities:
            if not isinstance(item, EvidenceIdentity):
                raise ContractFailure(
                    "invalid_evidence_identity",
                    f"stage '{stage.id}' returned invalid evidence identity",
                )
            try:
                identity = EvidenceIdentity(
                    name=item.name,
                    role=item.role,
                    digest=item.digest,
                )
            except Exception as exc:
                raise ContractFailure(
                    "invalid_evidence_identity",
                    f"stage '{stage.id}' returned invalid evidence identity",
                ) from exc
            if not is_token(identity.name) or not is_token(identity.role):
                raise ContractFailure(
                    "invalid_evidence_identity",
                    f"stage '{stage.id}' returned invalid evidence identity",
                )
            if not is_sha256_digest(identity.digest):
                raise ContractFailure(
                    "invalid_evidence_identity",
                    f"stage '{stage.id}' returned invalid evidence digest",
                )
            if identity.name in validated:
                raise ContractFailure(
                    "duplicate_evidence_identity",
                    f"stage '{stage.id}' returned duplicate evidence "
                    f"'{identity.name}'",
                )
            validated[identity.name] = identity
        missing = sorted(
            f"{name}:{role}"
            for name, role in stage.produced_evidence.items()
            if name not in validated or validated[name].role != role
        )
        if missing:
            raise ContractFailure(
                "missing_producer_evidence",
                f"stage '{stage.id}' did not return declared evidence: {', '.join(missing)}",
            )
        return tuple(validated.values())

    @staticmethod
    def _require_evidence(
        stage: StageSpec,
        evidence_by_stage: Mapping[str, tuple[EvidenceIdentity, ...]],
    ) -> tuple[tuple[EvidenceBinding, str], ...]:
        required = []
        missing = []
        for binding in stage.evidence_bindings:
            item = next(
                (
                    item
                    for item in evidence_by_stage.get(binding.stage, ())
                    if item.name == binding.name and item.role == binding.role
                ),
                None,
            )
            if item is None:
                missing.append(f"{binding.stage}/{binding.name}:{binding.role}")
            else:
                required.append((binding, item.digest))
        if missing:
            raise ContractFailure(
                "missing_required_evidence",
                f"stage '{stage.id}' requires evidence: {', '.join(missing)}",
            )
        return tuple(required)

    def _recover(
        self,
        completed: list[tuple[StageSpec, RecoveryRequest | None]],
        records: list[StageRecord],
        capabilities: Mapping[str, AdapterCapabilities],
    ) -> bool:
        recovery_blocked = False
        record_indexes = {
            record.stage_id: index for index, record in enumerate(records)
        }
        for stage, recovery_request in reversed(completed):
            index = record_indexes[stage.id]
            if recovery_blocked:
                records[index] = replace(
                    records[index],
                    recovery_status="blocked",
                    recovery_reason_code="blocked_by_later_recovery",
                )
                continue
            if recovery_request is None:
                records[index] = replace(
                    records[index],
                    recovery_status="not_declared",
                    recovery_reason_code="recovery_not_declared",
                )
                recovery_blocked = True
                continue
            pair = (recovery_request.operation, recovery_request.recovery_operation)
            if pair not in capabilities[stage.adapter].owned_cleanup:
                records[index] = replace(
                    records[index],
                    recovery_status="blocked",
                    recovery_reason_code="recovery_effect_unverified",
                )
                recovery_blocked = True
                continue
            try:
                recovery = self._adapters[stage.adapter].recover(recovery_request)
            except Exception:  # noqa: BLE001 - adapter boundary
                recovery = RecoveryResult(
                    succeeded=False,
                    reason_code="adapter_recovery_error",
                )
            if not isinstance(recovery, RecoveryResult) or type(
                recovery.succeeded
            ) is not bool:
                recovery = RecoveryResult(
                    succeeded=False,
                    reason_code="invalid_recovery_result",
                )
            else:
                try:
                    self._validate_reason_code(
                        stage.id,
                        recovery.reason_code,
                        "recovery",
                    )
                except ContractFailure:
                    recovery = RecoveryResult(
                        succeeded=False,
                        reason_code="invalid_recovery_result",
                    )
            if not recovery.succeeded:
                recovery_blocked = True
            records[index] = replace(
                records[index],
                recovery_status="succeeded" if recovery.succeeded else "failed",
                recovery_reason_code=(
                    "" if recovery.succeeded else "adapter_recovery_failed"
                ),
                adapter_recovery_reason_code=recovery.reason_code,
                recovery_result=(
                    "stage recovery completed"
                    if recovery.succeeded
                    else "stage recovery failed"
                ),
            )
        return recovery_blocked

    @staticmethod
    def _recovery_request(
        spec: ContinuityContract,
        stage: StageSpec,
        inputs: Mapping[str, Any],
        outputs: Mapping[str, Any],
    ) -> RecoveryRequest | None:
        if stage.recovery_operation is None:
            return None
        return RecoveryRequest(
            operation_id=spec.operation_id,
            stage_id=stage.id,
            operation=stage.operation,
            recovery_operation=stage.recovery_operation,
            inputs=inputs,
            outputs=outputs,
        )

    def _stage_record(
        self,
        stage: StageSpec,
        *,
        capabilities: AdapterCapabilities,
        status: str,
        reason_code: str = "",
        adapter_reason_code: str = "",
        result: str = "",
        authority: AuthorityAdmission | None = None,
        outputs: Mapping[str, Any] | None = None,
        evidence: tuple[EvidenceIdentity, ...] = (),
    ) -> StageRecord:
        try:
            output_identities = tuple(
                OutputIdentity(name=name, digest=json_digest(outputs[name]))
                for name in sorted(stage.publish)
                if outputs is not None and name in outputs
            )
        except (ValueError, TypeError, RecursionError) as exc:
            raise ContractFailure(
                "invalid_stage_outputs",
                f"stage '{stage.id}' returned invalid outputs",
            ) from exc
        return StageRecord(
            stage_id=stage.id,
            adapter=capabilities.identity,
            adapter_operations=capabilities.operations,
            operation=stage.operation,
            status=status,
            reason_code=reason_code,
            adapter_reason_code=adapter_reason_code,
            result=result,
            authority_receipt=authority,
            outputs=output_identities,
            evidence=evidence,
        )

    @staticmethod
    def _authority_evidence(receipt: AuthorityReceipt) -> AuthorityAdmission:
        return AuthorityAdmission(
            logical_ref=receipt.logical_ref,
            capability=receipt.capability,
            provider=receipt.provider,
            provider_identity=AuthorityProviderProvenance(
                source=receipt.provider_identity.source,
                distribution=receipt.provider_identity.distribution,
                version=receipt.provider_identity.version,
                entry_point=receipt.provider_identity.entry_point,
                contract_version=receipt.provider_identity.contract_version,
            ),
        )

    def _terminal(
        self,
        spec: ContinuityContract,
        *,
        contract_digest: str,
        status: str,
        closure: str,
        reason_code: str,
        result: str,
        started_at: str,
        records: list[StageRecord],
    ) -> TerminalRecord:
        return TerminalRecord(
            operation_id=spec.operation_id,
            contract_schema_version=spec.schema_version,
            contract_digest=contract_digest,
            controller=self._controller_identity,
            workload=spec.workload,
            status=status,
            closure=closure,
            reason_code=reason_code,
            result=result,
            started_at=started_at,
            completed_at=self._timestamp(),
            stages=tuple(records),
        )

    def _publish_terminal(
        self,
        lease: OperationLease,
        record: TerminalRecord,
    ) -> tuple[PublicationState, Exception | None]:
        try:
            self._operation_store.publish(lease, record.to_evidence())
        except Exception as exc:  # noqa: BLE001 - operation-store boundary
            return self._probe_publication(lease, record), exc
        return PublicationState.COMMITTED, None

    def _claim(
        self,
        spec: ContinuityContract,
        contract_digest: str,
        started_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "kind": "ContinuityOperationClaim",
            "operation_id": spec.operation_id,
            "contract": {
                "schema_version": spec.schema_version,
                "digest": contract_digest,
            },
            "controller": self._controller_identity.to_evidence(),
            "workload": spec.workload.to_evidence(),
            "started_at": started_at,
        }

    @staticmethod
    def _validate_reason_code(
        stage_id: str,
        reason_code: str,
        phase: str,
    ) -> None:
        if not isinstance(reason_code, str) or (
            reason_code and not is_token(reason_code)
        ):
            raise ContractFailure(
                f"invalid_{phase}_result",
                f"stage '{stage_id}' returned an invalid {phase} reason code",
            )

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
