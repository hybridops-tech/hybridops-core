"""Create and verify the original reference binding for a contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from hyops.continuity.api import ApiResource, ApiSpec, v1alpha1
from hyops.continuity.json_values import digest_json
from hyops.continuity.validation import is_sha256_digest

from .client import (
    DISPATCH_ANNOTATION,
    TERMINAL_ANNOTATION,
    ContractClient,
    StatusConflict,
)
from .references import (
    ReferenceBindingError,
    read_bound_subject,
    resolve_references,
    verify_references,
)


def _record_name(contract_uid: str) -> str:
    digest = hashlib.sha256(contract_uid.encode()).hexdigest()
    return f"binding-{digest[:32]}.{digest[32:]}"


def _operation_key(prefix: str, contract_uid: str) -> str:
    return prefix + "-" + hashlib.sha256(contract_uid.encode()).hexdigest()[:54]


@dataclass(frozen=True)
class BindingReceipt:
    namespace: str
    name: str
    contract_uid: str
    record_uid: str
    digest: str

    @property
    def record_name(self) -> str:
        return _record_name(self.contract_uid)

    @property
    def operation_id(self) -> str:
        return _operation_key("dispatch", self.contract_uid)

    @property
    def terminal_name(self) -> str:
        return _operation_key("terminal", self.contract_uid)


def require_separate_store(record_namespace: str, namespace: str) -> None:
    if not record_namespace or not namespace or record_namespace == namespace:
        raise ReferenceBindingError("InvalidBindingNamespace")


def read_binding_record(
    client: ContractClient,
    namespace: str,
    key: str,
    *,
    missing_reason: str = "BindingMissing",
) -> tuple[dict, dict]:
    obj = client.read_binding(namespace, key)
    if obj is None:
        raise ReferenceBindingError(missing_reason)
    return obj["metadata"], _record_body(obj)


def _record_body(obj: dict) -> dict:
    try:
        record = json.loads(obj["data"]["binding.json"])
    except (ValueError, RecursionError):
        raise ReferenceBindingError("InvalidBindingRecord") from None
    if not isinstance(record, dict):
        raise ReferenceBindingError("InvalidBindingRecord")
    return record


def bind_operation(
    client: ContractClient, record_namespace: str, namespace: str, name: str
) -> BindingReceipt:
    """Create the baseline once; on duplicate delivery verify the original."""
    require_separate_store(record_namespace, namespace)
    record = resolve_references(client, namespace, name)
    uid = record["contract"]["uid"]
    key = _record_name(uid)
    try:
        created = client.create_binding(record_namespace, key, record)
    except FileExistsError:
        metadata, record = read_binding_record(client, record_namespace, key)
        record_uid = metadata["uid"]
        if (
            not isinstance(record.get("contract"), dict)
            or record["contract"].get("uid") != uid
        ):
            raise ReferenceBindingError("BindingChanged") from None
        verify_references(client, namespace, name, record)
    else:
        record_uid = created["metadata"]["uid"]
    return BindingReceipt(namespace, name, uid, record_uid, digest_json(record))


def _pinned_record(
    client: ContractClient, record_namespace: str, receipt: BindingReceipt
) -> tuple[dict, dict]:
    metadata, record = read_binding_record(
        client, record_namespace, receipt.record_name
    )
    if metadata["uid"] != receipt.record_uid:
        raise ReferenceBindingError("BindingReplaced")
    subject = record.get("contract")
    if not isinstance(subject, dict) or (
        (subject.get("namespace"), subject.get("name"), subject.get("uid"))
        != (receipt.namespace, receipt.name, receipt.contract_uid)
        or digest_json(record) != receipt.digest
    ):
        raise ReferenceBindingError("BindingChanged")
    return metadata, record


def _annotations(metadata: dict) -> dict:
    annotations = metadata.get("annotations", {})
    if not isinstance(annotations, dict):
        raise ReferenceBindingError("InvalidBindingRecord")
    return annotations


def _dispatch_record(receipt: BindingReceipt) -> dict:
    return {
        "apiVersion": v1alpha1.API_VERSION_VALUE,
        "kind": "DispatchClaim",
        "operationId": receipt.operation_id,
        "contractUid": receipt.contract_uid,
        "bindingUid": receipt.record_uid,
        "bindingDigest": receipt.digest,
    }


def dispatched_receipt(
    client: ContractClient, record_namespace: str, namespace: str, name: str, uid: str
) -> BindingReceipt | None:
    """Recover the binding identity from the protected dispatch claim without rebinding."""
    require_separate_store(record_namespace, namespace)
    obj = client.read_binding(record_namespace, _operation_key("dispatch", uid))
    if obj is None:
        binding = client.read_binding(record_namespace, _record_name(uid))
        if binding is not None and {
            DISPATCH_ANNOTATION,
            TERMINAL_ANNOTATION,
        }.intersection(_annotations(binding["metadata"])):
            raise ReferenceBindingError("DispatchClaimMissing")
        if (
            client.read_binding(record_namespace, _operation_key("terminal", uid))
            is not None
        ):
            raise ReferenceBindingError("DispatchClaimMissing")
        return None
    claim = _record_body(obj)
    binding_uid, digest = claim.get("bindingUid"), claim.get("bindingDigest")
    if not (
        isinstance(binding_uid, str)
        and binding_uid.strip()
        and binding_uid == binding_uid.strip()
        and is_sha256_digest(digest)
    ):
        raise ReferenceBindingError("DispatchClaimChanged")
    receipt = BindingReceipt(namespace, name, uid, binding_uid, digest)
    if claim != _dispatch_record(receipt):
        raise ReferenceBindingError("DispatchClaimChanged")
    return receipt


def claim_dispatch(
    client: ContractClient, record_namespace: str, receipt: BindingReceipt
) -> str:
    require_separate_store(record_namespace, receipt.namespace)
    metadata, _ = _pinned_record(client, record_namespace, receipt)
    if DISPATCH_ANNOTATION in _annotations(metadata):
        raise ReferenceBindingError("DispatchAlreadyClaimed")
    try:
        claim = client.create_binding(
            record_namespace, receipt.operation_id, _dispatch_record(receipt)
        )
    except FileExistsError:
        raise ReferenceBindingError("DispatchAlreadyClaimed") from None
    try:
        client.mark_dispatch(
            record_namespace,
            receipt.record_name,
            receipt.record_uid,
            metadata["resourceVersion"],
            receipt.operation_id,
        )
    except StatusConflict:
        raise ReferenceBindingError("DispatchConflict") from None
    return claim["metadata"]["uid"]


def _verify_claim(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    metadata: dict,
    claim_uid: str,
) -> None:
    claim_meta, claim = read_binding_record(
        client, record_namespace, receipt.operation_id
    )
    if (
        _annotations(metadata).get(DISPATCH_ANNOTATION) != receipt.operation_id
        or claim_meta["uid"] != claim_uid
        or claim != _dispatch_record(receipt)
    ):
        raise ReferenceBindingError("DispatchClaimChanged")


def read_dispatched_subject(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    claim_uid: str,
) -> tuple[dict, ApiResource]:
    require_separate_store(record_namespace, receipt.namespace)
    metadata, record = _pinned_record(client, record_namespace, receipt)
    _verify_claim(client, record_namespace, receipt, metadata, claim_uid)
    resource = read_bound_subject(
        client, receipt.namespace, receipt.name, record["contract"]
    )
    return metadata, resource


def verify_operation(
    client: ContractClient,
    record_namespace: str,
    receipt: BindingReceipt,
    *,
    claim_uid: str | None = None,
) -> ApiSpec:
    """Verify from the original receipt. A missing baseline is never recreated."""
    require_separate_store(record_namespace, receipt.namespace)
    _, record = _pinned_record(client, record_namespace, receipt)
    spec = verify_references(client, receipt.namespace, receipt.name, record)
    metadata, _ = _pinned_record(client, record_namespace, receipt)
    if claim_uid is not None:
        _verify_claim(client, record_namespace, receipt, metadata, claim_uid)
    return spec
