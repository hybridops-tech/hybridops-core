"""Create and verify the original reference binding for a contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from hyops.continuity.json_values import digest_json

from .client import ContractClient
from .references import ReferenceBindingError, resolve_references, verify_references


def _record_name(contract_uid: str) -> str:
    digest = hashlib.sha256(contract_uid.encode()).hexdigest()
    return f"binding-{digest[:32]}.{digest[32:]}"


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


def _separate_store(record_namespace: str, namespace: str) -> None:
    if not record_namespace or not namespace or record_namespace == namespace:
        raise ReferenceBindingError("InvalidBindingNamespace")


def _load(client: ContractClient, namespace: str, key: str) -> tuple[str, dict]:
    obj = client.read_binding(namespace, key)
    if obj is None:
        raise ReferenceBindingError("BindingMissing")
    try:
        record = json.loads(obj["data"]["binding.json"])
    except (ValueError, RecursionError):
        raise ReferenceBindingError("InvalidBindingRecord") from None
    if not isinstance(record, dict):
        raise ReferenceBindingError("InvalidBindingRecord")
    return obj["metadata"]["uid"], record


def bind_operation(
    client: ContractClient, record_namespace: str, namespace: str, name: str
) -> BindingReceipt:
    """Create the baseline once; on duplicate delivery verify the original."""
    _separate_store(record_namespace, namespace)
    record = resolve_references(client, namespace, name)
    uid = record["contract"]["uid"]
    key = _record_name(uid)
    try:
        created = client.create_binding(record_namespace, key, record)
    except FileExistsError:
        record_uid, record = _load(client, record_namespace, key)
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
) -> dict:
    record_uid, record = _load(client, record_namespace, receipt.record_name)
    if record_uid != receipt.record_uid:
        raise ReferenceBindingError("BindingReplaced")
    subject = record.get("contract")
    if not isinstance(subject, dict) or (
        (subject.get("namespace"), subject.get("name"), subject.get("uid"))
        != (receipt.namespace, receipt.name, receipt.contract_uid)
        or digest_json(record) != receipt.digest
    ):
        raise ReferenceBindingError("BindingChanged")
    return record


def verify_operation(
    client: ContractClient, record_namespace: str, receipt: BindingReceipt
) -> None:
    """Verify from the original receipt. A missing baseline is never recreated."""
    _separate_store(record_namespace, receipt.namespace)
    record = _pinned_record(client, record_namespace, receipt)
    verify_references(client, receipt.namespace, receipt.name, record)
    _pinned_record(client, record_namespace, receipt)
