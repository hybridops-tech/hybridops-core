"""Retain a bound execution result and publish status from its pinned evidence."""

import hashlib
import json

from hyops.continuity.api import ApiResource, v1alpha1
from hyops.continuity.engine import ContinuityEngine
from hyops.continuity.models import TerminalRecord
from hyops.continuity.storage import encode_store_record
from hyops.continuity.validation import is_sha256_digest

from .binding import (
    BindingReceipt,
    read_binding_record,
    read_dispatched_subject,
    require_separate_store,
)
from .client import TERMINAL_ANNOTATION, ContractClient, StatusConflict
from .execution import execute_with_claim, project_contract
from .references import ReferenceBindingError
from .terminal_projection import terminal_status


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _verify_record(
    record: dict, resource: ApiResource, receipt: BindingReceipt
) -> None:
    contract = project_contract(resource.spec, receipt.operation_id)
    if not isinstance(record, dict) or (
        record.get("operation_id") != contract.operation_id
        or record.get("workload") != contract.workload.to_evidence()
        or record.get("contract")
        != {"schema_version": contract.schema_version, "digest": contract.digest()}
    ):
        raise ReferenceBindingError("TerminalRecordMismatch")


def _witness(
    receipt: BindingReceipt,
    generation: int,
    claim_uid: str,
    evidence_uid: str,
    digest: str,
) -> dict:
    return {
        "apiVersion": v1alpha1.API_VERSION_VALUE,
        "kind": "TerminalWitness",
        "contractUid": receipt.contract_uid,
        "generation": generation,
        "bindingUid": receipt.record_uid,
        "bindingDigest": receipt.digest,
        "claimUid": claim_uid,
        "evidenceUid": evidence_uid,
        "digest": digest,
    }


def _evidence_content(
    client: ContractClient, namespace: str, name: str, uid: str, digest: str
) -> bytes:
    evidence = client.read_terminal_evidence(namespace, name)
    if evidence is None or evidence["metadata"]["uid"] != uid:
        raise ReferenceBindingError("TerminalEvidenceMissingOrReplaced")
    content = evidence["data"]["terminal.json"].encode("utf-8")
    if _digest(content) != digest:
        raise ReferenceBindingError("TerminalEvidenceDigestMismatch")
    return content


def _pin_witness(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    witness: dict,
    witness_uid: str,
) -> None:
    name = receipt.terminal_name
    for attempt in range(3):
        meta, _ = read_dispatched_subject(
            client, record_namespace, receipt, witness["claimUid"]
        )
        witness_meta, stored = read_binding_record(
            client, record_namespace, name, missing_reason="TerminalWitnessMissing"
        )
        if (
            witness_meta["uid"] != witness_uid
            or type(stored.get("generation")) is not int
            or stored != witness
        ):
            raise ReferenceBindingError("TerminalWitnessChanged")
        _evidence_content(
            client, receipt.namespace, name, witness["evidenceUid"], witness["digest"]
        )
        annotations = meta.get("annotations", {})
        if TERMINAL_ANNOTATION in annotations:
            if annotations[TERMINAL_ANNOTATION] != witness_uid:
                raise ReferenceBindingError("TerminalWitnessChanged")
            return
        try:
            client.pin_terminal_witness(
                record_namespace,
                receipt.record_name,
                receipt.record_uid,
                meta["resourceVersion"],
                witness_uid,
            )
        except StatusConflict:
            if attempt == 2:
                raise
        else:
            return


def run_and_retain_terminal(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    engine: ContinuityEngine,
) -> TerminalRecord:
    require_separate_store(record_namespace, receipt.namespace)
    name = receipt.terminal_name
    if (
        client.read_terminal_evidence(receipt.namespace, name) is not None
        or client.read_binding(record_namespace, name) is not None
    ):
        raise ReferenceBindingError("TerminalRecordAlreadyExists")
    result, claim_uid = execute_with_claim(client, record_namespace, receipt, engine)
    meta, resource = read_dispatched_subject(
        client, record_namespace, receipt, claim_uid
    )
    if TERMINAL_ANNOTATION in meta.get("annotations", {}):
        raise ReferenceBindingError("TerminalAlreadyWitnessed")
    record = result.to_evidence()
    _verify_record(record, resource, receipt)
    payload = encode_store_record(record)
    if len(payload) > 1024 * 1024:
        raise ReferenceBindingError("TerminalEvidenceTooLarge")
    digest = _digest(payload)
    public = client.create_terminal_evidence(
        receipt.namespace, name, payload.decode("utf-8")
    )
    witness = _witness(
        receipt,
        resource.metadata.generation,
        claim_uid,
        public["metadata"]["uid"],
        digest,
    )
    stored = client.create_binding(record_namespace, name, witness)
    _pin_witness(client, record_namespace, receipt, witness, stored["metadata"]["uid"])
    return result


def _publication(
    client: ContractClient, record_namespace: str, receipt: BindingReceipt
) -> tuple[ApiResource, dict, bool]:
    require_separate_store(record_namespace, receipt.namespace)
    name = receipt.terminal_name
    witness_meta, witness = read_binding_record(
        client, record_namespace, name, missing_reason="TerminalWitnessMissing"
    )
    claim_uid, evidence_uid, digest = (
        witness.get(key) for key in ("claimUid", "evidenceUid", "digest")
    )
    if not all(
        isinstance(uid, str) and uid.strip() for uid in (claim_uid, evidence_uid)
    ) or not is_sha256_digest(digest):
        raise ReferenceBindingError("InvalidTerminalWitness")
    meta, resource = read_dispatched_subject(
        client, record_namespace, receipt, claim_uid
    )
    generation = resource.metadata.generation
    if (
        meta.get("annotations", {}).get(TERMINAL_ANNOTATION) != witness_meta["uid"]
        or type(witness.get("generation")) is not int
        or witness != _witness(receipt, generation, claim_uid, evidence_uid, digest)
    ):
        raise ReferenceBindingError("TerminalWitnessChanged")
    content = _evidence_content(client, receipt.namespace, name, evidence_uid, digest)
    try:
        record = json.loads(content)
    except (ValueError, RecursionError):
        raise ReferenceBindingError("InvalidTerminalRecord") from None
    _verify_record(record, resource, receipt)
    proposed = terminal_status(resource, record, name, digest)
    terminal = (
        resource.status is not None and resource.status.terminal_evidence is not None
    )
    if terminal and resource.status != v1alpha1.decode_status(
        proposed, generation, resource.spec.recovery_sets
    ):
        raise ReferenceBindingError("TerminalStatusConflict")
    return resource, proposed, terminal


def publish_terminal_status(
    client: ContractClient, record_namespace: str, receipt: BindingReceipt
) -> bool:
    """Verify the stored record on every attempt, including an already-terminal read."""
    for attempt in range(3):
        resource, status, terminal = _publication(client, record_namespace, receipt)
        if terminal:
            return False
        try:
            client.replace_terminal_status(
                receipt.namespace,
                receipt.name,
                receipt.contract_uid,
                resource.metadata.extra["resourceVersion"],
                status,
                recovery_sets=resource.spec.recovery_sets,
            )
        except StatusConflict:
            if attempt == 2:
                raise
            continue
        _, _, terminal = _publication(client, record_namespace, receipt)
        if not terminal:
            raise ReferenceBindingError("TerminalStatusUnconfirmed")
        return True
