"""Project a committed engine record into the contract's terminal status."""

from dataclasses import replace

from hyops.continuity.api import (
    ApiResource,
    ApiStatus,
    RecoverySetIdentity,
    TerminalEvidenceReference,
    v1alpha1,
)
from hyops.continuity.models import TERMINAL_RECORD_SCHEMA_VERSION
from hyops.continuity.validation import is_sha256_digest, is_token

from .references import ReferenceBindingError


def _invalid() -> ReferenceBindingError:
    return ReferenceBindingError("InvalidTerminalRecord")


def _outcome(record: dict) -> str:
    if not isinstance(record, dict) or (
        record.get("schema_version") != TERMINAL_RECORD_SCHEMA_VERSION
        or record.get("kind") != "ContinuityOperationRecord"
        or not isinstance(record.get("stages"), list)
    ):
        raise _invalid()
    match record.get("status"), record.get("closure"):
        case "succeeded", "completed":
            return "Succeeded"
        case "recovered", "recovered":
            return "Recovered"
        case "failed", ("none" | "recovery_failed"):
            return "Failed"
        case _:
            raise _invalid()


def _stage_evidence(items: object) -> dict:
    if not isinstance(items, list):
        raise _invalid()
    evidence = {}
    for item in items:
        if not isinstance(item, dict) or (
            not is_token(item.get("name"))
            or not is_token(item.get("role"))
            or not is_sha256_digest(item.get("digest"))
            or item["name"] in evidence
        ):
            raise _invalid()
        evidence[item["name"]] = item
    return evidence


def _producer_sets(
    resource: ApiResource, record: dict, phase: str
) -> tuple[RecoverySetIdentity, ...]:
    stages = {s.id for s in resource.spec.stages}
    attempted = set()
    outputs = {}
    for step in record["stages"]:
        if not isinstance(step, dict) or not is_token(step.get("stage_id")):
            raise _invalid()
        stage_id = step["stage_id"]
        if stage_id not in stages or stage_id in attempted:
            raise _invalid()
        attempted.add(stage_id)
        evidence = _stage_evidence(step.get("evidence", []))
        if step.get("status") == "succeeded":
            outputs[stage_id] = evidence
        elif step.get("status") not in ("failed", "denied") or evidence:
            raise _invalid()
    if phase == "Succeeded" and outputs.keys() != stages:
        raise _invalid()
    if phase == "Recovered":
        cleanup = [step.get("recovery_status") for step in record["stages"]]
        if "succeeded" not in cleanup or any(
            value not in ("succeeded", "not_required") for value in cleanup
        ):
            raise _invalid()
    if record["closure"] == "recovery_failed" and not attempted:
        raise _invalid()
    result = []
    for declaration in resource.spec.recovery_sets:
        if declaration.stage not in outputs:
            continue
        item = outputs[declaration.stage].get(declaration.evidence)
        if item is None or item["role"] != declaration.role:
            raise _invalid()
        result.append(
            RecoverySetIdentity(
                declaration.name, item["name"], item["role"], item["digest"]
            )
        )
    return tuple(result)


def terminal_status(
    resource: ApiResource, record: dict, evidence_name: str, evidence_digest: str
) -> dict:
    phase = _outcome(record)
    identities = _producer_sets(resource, record, phase)
    previous = resource.status or ApiStatus()
    if not set(previous.recovery_sets).issubset(identities):
        raise ReferenceBindingError("RecoverySetConflict")
    proposed = replace(
        previous,
        observed_generation=resource.metadata.generation,
        phase=phase,
        recovery_sets=identities,
        terminal_evidence=TerminalEvidenceReference(
            "", "ConfigMap", evidence_name, evidence_digest
        ),
    )
    return v1alpha1.encode(replace(resource, status=proposed))["status"]
