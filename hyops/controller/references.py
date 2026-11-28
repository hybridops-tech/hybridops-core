"""Bind namespaced continuity references to observed Kubernetes object identities."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any, Protocol

from hyops.continuity.api import ApiResource, ApiSpec, v1alpha1
from hyops.continuity.json_values import digest_json


class ReferenceClient(Protocol):
    def read(self, namespace: str, name: str) -> Mapping[str, Any] | None: ...

    def read_reference(
        self, namespace: str, kind: str, name: str
    ) -> Mapping[str, Any] | None: ...


class ReferenceBindingError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _identity(obj: Mapping[str, Any], namespace: str, name: str) -> dict[str, str]:
    meta = obj.get("metadata")
    if not isinstance(meta, Mapping) or (
        meta.get("namespace") != namespace
        or meta.get("name") != name
        or not _identifier(meta.get("uid"))
        or not _identifier(meta.get("resourceVersion"))
    ):
        raise ReferenceBindingError("InvalidObjectIdentity")
    if meta.get("deletionTimestamp") is not None:
        raise ReferenceBindingError("ObjectDeleting")
    return {key: meta[key] for key in ("namespace", "name", "uid", "resourceVersion")}


def _read_contract(
    client: ReferenceClient, namespace: str, name: str
) -> tuple[dict, ApiResource]:
    obj = client.read(namespace, name)
    if obj is None:
        raise ReferenceBindingError("ContractMissing")
    if not isinstance(obj, Mapping):
        raise ReferenceBindingError("InvalidContract")
    identity = _identity(obj, namespace, name)
    try:
        parsed = v1alpha1.decode(obj)
    except v1alpha1.ApiValidationError:
        raise ReferenceBindingError("InvalidContract") from None
    return dict(
        identity,
        generation=parsed.metadata.generation,
        specDigest=digest_json(obj["spec"]),
    ), parsed


def _contract(
    client: ReferenceClient, namespace: str, name: str
) -> tuple[dict, ApiSpec]:
    identity, resource = _read_contract(client, namespace, name)
    if resource.metadata.generation < 1 or (
        resource.status and resource.status.phase != "Pending"
    ):
        raise ReferenceBindingError("ContractNotPending")
    return identity, resource.spec


def _keys(spec: ApiSpec) -> list[tuple[str, str]]:
    sites = [
        spec.workload.ref,
        *(a.parameters_ref for a in spec.authorities),
        *(s.parameters_ref for s in spec.stages),
    ]
    if any(
        r.api_group or r.kind not in ("ConfigMap", "Secret")
        for r in sites
        if r is not None
    ):
        raise ReferenceBindingError("UnsupportedReference")
    return sorted({(r.kind, r.name) for r in sites if r is not None})


def _config_digest(obj: Mapping[str, Any]) -> str:
    data, binary = obj.get("data", {}), obj.get("binaryData", {})
    for fields in (data, binary):
        if not isinstance(fields, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in fields.items()
        ):
            raise ReferenceBindingError("InvalidConfigMap")
    if not data.keys().isdisjoint(binary):
        raise ReferenceBindingError("InvalidConfigMap")
    try:
        for value in binary.values():
            if (
                base64.b64encode(base64.b64decode(value, validate=True)).decode("ascii")
                != value
            ):
                raise ValueError
        return digest_json({"data": data, "binaryData": binary})
    except ValueError:
        raise ReferenceBindingError("InvalidConfigMap") from None


def _referent(client: ReferenceClient, namespace: str, kind: str, name: str) -> dict:
    obj = client.read_reference(namespace, kind, name)
    if obj is None:
        raise ReferenceBindingError("ReferenceMissing")
    if not isinstance(obj, Mapping):
        raise ReferenceBindingError("InvalidReference")
    expected_type = (
        ("v1", "ConfigMap")
        if kind == "ConfigMap"
        else ("meta.k8s.io/v1", "PartialObjectMetadata")
    )
    if (obj.get("apiVersion"), obj.get("kind")) != expected_type:
        raise ReferenceBindingError("InvalidReference")
    result = dict(_identity(obj, namespace, name), apiVersion="v1", kind=kind)
    if kind == "ConfigMap":
        result["contentDigest"] = _config_digest(obj)
    elif obj.keys() - {"apiVersion", "kind", "metadata"}:
        raise ReferenceBindingError("InvalidSecretMetadata")
    return result


def _same_contract(observed: dict, original: object) -> bool:
    # Status writes advance the contract resourceVersion without changing its operation.
    return (
        isinstance(original, dict)
        and _identifier(original.get("resourceVersion"))
        and type(original.get("generation")) is int
        and observed == dict(original, resourceVersion=observed["resourceVersion"])
    )


def read_bound_subject(
    client: ReferenceClient, namespace: str, name: str, subject: dict
) -> ApiResource:
    identity, resource = _read_contract(client, namespace, name)
    if not _same_contract(identity, subject):
        raise ReferenceBindingError("ContractChanged")
    return resource


def _observe(
    client: ReferenceClient, namespace: str, name: str, baseline: dict | None
) -> tuple[dict[str, Any], ApiSpec]:
    first, spec = _contract(client, namespace, name)
    if baseline is not None and not _same_contract(first, baseline):
        raise ReferenceBindingError("ContractChanged")
    refs = [_referent(client, namespace, kind, key) for kind, key in _keys(spec)]
    current, _ = _contract(client, namespace, name)
    if not _same_contract(current, first):
        raise ReferenceBindingError("ContractChanged")
    return {
        "apiVersion": v1alpha1.API_VERSION_VALUE,
        "kind": "ResolvedOperation",
        "contract": current,
        "references": refs,
    }, spec


def resolve_references(
    client: ReferenceClient, namespace: str, name: str
) -> dict[str, Any]:
    record, _ = _observe(client, namespace, name, None)
    return record


def verify_references(
    client: ReferenceClient, namespace: str, name: str, record: Mapping[str, Any]
) -> ApiSpec:
    if not isinstance(record, Mapping) or (
        set(record) != {"apiVersion", "kind", "contract", "references"}
        or record["apiVersion"] != v1alpha1.API_VERSION_VALUE
        or record["kind"] != "ResolvedOperation"
        or not isinstance(record["contract"], dict)
        or not isinstance(record["references"], list)
    ):
        raise ReferenceBindingError("InvalidBindingRecord")
    current, spec = _observe(client, namespace, name, record["contract"])
    if current["references"] != record["references"]:
        raise ReferenceBindingError("ReferenceChanged")
    return spec
