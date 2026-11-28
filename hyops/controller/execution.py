"""Dispatch a pending Kubernetes contract from its original binding receipt."""

from hyops.authority.models import AuthorityDeclaration, AuthorityRequirement
from hyops.continuity.api import ApiPolicy, ApiSpec
from hyops.continuity.engine import ContinuityEngine
from hyops.continuity.models import (
    ContinuityContract,
    InputBinding,
    StageSpec,
    TerminalRecord,
    WorkloadIdentity,
)

from .binding import (
    BindingReceipt,
    claim_dispatch,
    read_dispatched_subject,
    verify_operation,
)
from .client import TERMINAL_FINALIZER, ContractClient, StatusConflict
from .references import ReferenceBindingError, finalizers


def project_contract(spec: ApiSpec, operation_id: str) -> ContinuityContract:
    """Translate a verified, self-contained API spec into its execution graph."""
    if spec.workload.ref is not None or any(
        entry.parameters_ref is not None for entry in (*spec.authorities, *spec.stages)
    ):
        raise ReferenceBindingError("UnsupportedExecutionReference")
    if spec.policy != ApiPolicy():
        raise ReferenceBindingError("UnsupportedExecutionPolicy")
    declarations = {
        a.name: AuthorityDeclaration(
            logical_ref=a.name,
            capability=a.capability,
            provider=a.provider,
            compatibility=a.compatibility,
        )
        for a in spec.authorities
    }
    requirements = {
        name: AuthorityRequirement(name, a.capability, a.compatibility)
        for name, a in declarations.items()
    }
    produced = spec.producer_evidence_by_stage()
    required = spec.recovery_bindings_by_stage()
    return ContinuityContract(
        operation_id=operation_id,
        workload=WorkloadIdentity(
            spec.workload.name, spec.workload.revision, spec.workload.digest
        ),
        authorities=declarations,
        stages=tuple(
            StageSpec(
                id=s.id,
                adapter=s.adapter,
                operation=s.operation,
                requires=s.requires,
                input_bindings={
                    b.name: InputBinding(b.stage, b.output) for b in s.input_bindings
                },
                publish=s.publish,
                produced_evidence=produced[s.id],
                evidence_bindings=required[s.id],
                authority=requirements[s.authority_ref]
                if s.authority_ref is not None
                else None,
                destructive=s.destructive,
                recovery_operation=s.recovery_operation,
            )
            for s in spec.stages
        ),
    )


def run_bound_operation(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    engine: ContinuityEngine,
) -> TerminalRecord:
    record, _ = execute_with_claim(client, record_namespace, receipt, engine)
    return record


def execute_with_claim(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    engine: ContinuityEngine,
    *,
    retain_terminal: bool = False,
) -> tuple[TerminalRecord, str]:
    spec = verify_operation(client, record_namespace, receipt, protected=False)
    contract = project_contract(spec, receipt.operation_id)
    claim_uid = claim_dispatch(client, record_namespace, receipt)
    if retain_terminal:
        _protect_dispatch(client, record_namespace, receipt, claim_uid)

    def before_mutation() -> None:
        verify_operation(
            client,
            record_namespace,
            receipt,
            claim_uid=claim_uid,
            protected=retain_terminal,
        )

    return engine.run(contract, before_mutation=before_mutation), claim_uid


def _protect_dispatch(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    claim_uid: str,
) -> None:
    for attempt in range(3):
        _, resource = read_dispatched_subject(
            client, record_namespace, receipt, claim_uid
        )
        if resource.status and resource.status.phase != "Pending":
            raise ReferenceBindingError("ContractNotPending")
        metadata = resource.metadata.extra
        current = finalizers(metadata)
        if TERMINAL_FINALIZER in current:
            raise ReferenceBindingError("TerminalFinalizerPresent")
        try:
            client.replace_finalizers(
                receipt.namespace,
                receipt.name,
                receipt.contract_uid,
                metadata["resourceVersion"],
                [*current, TERMINAL_FINALIZER],
            )
            return
        except StatusConflict:
            if attempt == 2:
                raise
