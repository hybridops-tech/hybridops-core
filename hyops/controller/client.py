"""Namespaced Kubernetes transport for contracts, references and binding records."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from contextlib import closing
from http.client import HTTPConnection, HTTPResponse
from typing import Any

from hyops.continuity.api import API_GROUP, API_KIND, RecoverySetSpec
from hyops.continuity.api.v1alpha1 import (
    API_VERSION_VALUE,
    ApiValidationError,
    decode_status,
)

from .reconcile import StatusConflict

_METADATA_ACCEPT = "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"
_IDENTITY_FIELDS = ("namespace", "name", "uid", "resourceVersion")
_RESPONSE_LIMIT = 16 * 1024 * 1024
DISPATCH_ANNOTATION = f"{API_GROUP}/dispatch"
TERMINAL_ANNOTATION = f"{API_GROUP}/terminal-witness"


def _response_object(response: HTTPResponse) -> dict[str, Any] | None:
    body = response.read(_RESPONSE_LIMIT + 1)
    if len(body) > _RESPONSE_LIMIT:
        raise ValueError("Kubernetes API response exceeds the size limit")
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _validation_condition(status: dict[str, Any]) -> dict[str, Any] | None:
    generation = status.get("observedGeneration")
    conditions = status.get("conditions")
    if (
        type(generation) is not int
        or generation < 1
        or not isinstance(conditions, list)
    ):
        return None
    owned = [
        c
        for c in conditions
        if isinstance(c, dict) and c.get("type") == "ContractValid"
    ]
    if len(owned) != 1:
        return None
    condition_generation = owned[0].get("observedGeneration")
    if type(condition_generation) is not int or condition_generation != generation:
        return None
    return owned[0]


def _record(obj: dict, namespace: str, name: str, key: str) -> dict:
    meta, data = obj.get("metadata"), obj.get("data")
    if not (
        (obj.get("apiVersion"), obj.get("kind")) == ("v1", "ConfigMap")
        and isinstance(meta, dict)
        and (meta.get("namespace"), meta.get("name")) == (namespace, name)
        and all(
            isinstance(meta.get(k), str) and meta[k] and meta[k] == meta[k].strip()
            for k in ("uid", "resourceVersion")
        )
        and meta.get("deletionTimestamp") is None
        and obj.get("immutable") is True
        and obj.get("binaryData", {}) == {}
        and isinstance(data, dict)
        and data.keys() == {key}
        and isinstance(data[key], str)
    ):
        raise ValueError(f"invalid {key.removesuffix('.json')} ConfigMap")
    return obj


class ContractClient:
    def __init__(self, connect: Callable[[], HTTPConnection]) -> None:
        self.connect = connect

    def read(self, namespace: str, name: str) -> dict[str, Any] | None:
        return self._request("GET", namespace, name)

    def read_reference(
        self, namespace: str, kind: str, name: str
    ) -> dict[str, Any] | None:
        if kind == "ConfigMap":
            obj = self._request("GET", namespace, name, resource="configmaps")
            if obj is not None and (obj.get("apiVersion"), obj.get("kind")) != (
                "v1",
                "ConfigMap",
            ):
                raise ValueError("invalid ConfigMap response")
            return obj
        if kind != "Secret":
            raise ValueError("unsupported reference kind")
        obj = self._request(
            "GET", namespace, name, resource="secrets", accept=_METADATA_ACCEPT
        )
        if obj is None:
            return None
        meta = obj.get("metadata")
        if not (
            obj.keys() == {"apiVersion", "kind", "metadata"}
            and (obj["apiVersion"], obj["kind"])
            == ("meta.k8s.io/v1", "PartialObjectMetadata")
            and isinstance(meta, dict)
            and all(isinstance(meta.get(k), str) for k in _IDENTITY_FIELDS)
            and (
                meta.get("deletionTimestamp") is None
                or isinstance(meta["deletionTimestamp"], str)
            )
        ):
            raise ValueError("invalid Secret metadata response")
        return {
            **obj,
            "metadata": {
                k: meta[k]
                for k in (*_IDENTITY_FIELDS, "deletionTimestamp")
                if k in meta
            },
        }

    def read_binding(self, namespace: str, name: str) -> dict[str, Any] | None:
        return self._read_record(namespace, name, "binding.json")

    def read_terminal_evidence(
        self, namespace: str, name: str
    ) -> dict[str, Any] | None:
        return self._read_record(namespace, name, "terminal.json")

    def _read_record(
        self, namespace: str, name: str, key: str
    ) -> dict[str, Any] | None:
        obj = self.read_reference(namespace, "ConfigMap", name)
        return None if obj is None else _record(obj, namespace, name, key)

    def create_binding(
        self, namespace: str, name: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        content = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return self._create_record(namespace, name, "binding.json", content)

    def create_terminal_evidence(
        self, namespace: str, name: str, content: str
    ) -> dict[str, Any]:
        return self._create_record(namespace, name, "terminal.json", content)

    def _create_record(
        self, namespace: str, name: str, key: str, content: str
    ) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError(f"{key} must be text")
        data = {key: content}
        payload = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"namespace": namespace, "name": name},
            "immutable": True,
            "data": data,
        }
        obj = self._request("POST", namespace, name, payload, resource="configmaps")
        if obj is None or _record(obj, namespace, name, key)["data"] != data:
            raise RuntimeError(
                f"{key.removesuffix('.json')} ConfigMap creation was not confirmed"
            )
        return obj

    def mark_dispatch(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        operation_id: str,
    ) -> None:
        if not uid or not resource_version or not operation_id:
            raise ValueError(
                "a dispatch claim requires an object identity and operation ID"
            )
        self._mark_binding(
            namespace, name, uid, resource_version, DISPATCH_ANNOTATION, operation_id
        )

    def pin_terminal_witness(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        witness_uid: str,
    ) -> None:
        if not uid or not resource_version or not witness_uid:
            raise ValueError(
                "pinning a terminal witness requires both identities and a resource version"
            )
        self._mark_binding(
            namespace, name, uid, resource_version, TERMINAL_ANNOTATION, witness_uid
        )

    def _mark_binding(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        key: str,
        value: str,
    ) -> None:
        obj = self._request(
            "PATCH",
            namespace,
            name,
            {
                "metadata": {
                    "uid": uid,
                    "resourceVersion": resource_version,
                    "annotations": {key: value},
                }
            },
            resource="configmaps",
        )
        if obj is not None:
            meta = _record(obj, namespace, name, "binding.json")["metadata"]
            if (
                meta["uid"] == uid
                and isinstance(meta.get("annotations"), dict)
                and meta["annotations"].get(key) == value
            ):
                return
        label = (
            "dispatch claim" if key == DISPATCH_ANNOTATION else "terminal witness pin"
        )
        raise RuntimeError(f"{label} was not confirmed")

    def replace_status(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        status: dict[str, Any],
    ) -> None:
        expected = _validation_condition(status)
        if expected is None:
            raise ValueError(
                "expected one ContractValid condition for the observed generation"
            )
        observed = self._write_status(namespace, name, uid, resource_version, status)
        if _validation_condition(observed) != expected:
            raise RuntimeError("ContinuityContract status write was not confirmed")

    def replace_terminal_status(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        status: dict[str, Any],
        *,
        recovery_sets: tuple[RecoverySetSpec, ...] = (),
    ) -> None:
        generation = status.get("observedGeneration")
        expected = decode_status(status, generation, recovery_sets)
        if expected.terminal_evidence is None:
            raise ValueError("expected terminal status with an evidence reference")
        observed = self._write_status(namespace, name, uid, resource_version, status)
        try:
            confirmed = decode_status(observed, generation, recovery_sets) == expected
        except ApiValidationError:
            confirmed = False
        if not confirmed:
            raise RuntimeError(
                "ContinuityContract terminal status write was not confirmed"
            )

    def _write_status(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        if not uid or not resource_version:
            raise ValueError("a status write requires UID and resourceVersion")
        result = self._request(
            "PUT",
            namespace,
            name,
            {
                "apiVersion": API_VERSION_VALUE,
                "kind": API_KIND,
                "metadata": {
                    "namespace": namespace,
                    "name": name,
                    "uid": uid,
                    "resourceVersion": resource_version,
                },
                "status": status,
            },
        )
        metadata = result.get("metadata") if result else None
        observed = result.get("status") if result else None
        if not (
            result
            and result.get("apiVersion") == API_VERSION_VALUE
            and result.get("kind") == API_KIND
            and isinstance(metadata, dict)
            and (metadata.get("namespace"), metadata.get("name"), metadata.get("uid"))
            == (namespace, name, uid)
            and metadata.get("deletionTimestamp") is None
            and type(metadata.get("generation")) is int
            and metadata["generation"] == status["observedGeneration"]
            and isinstance(metadata.get("resourceVersion"), str)
            and metadata["resourceVersion"].strip()
            and isinstance(observed, dict)
            and observed.get("phase", "Pending") == status.get("phase", "Pending")
        ):
            raise RuntimeError("ContinuityContract status write was not confirmed")
        return observed

    def _request(
        self,
        method: str,
        namespace: str,
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        resource: str = "continuitycontracts",
        accept: str = "application/json",
    ) -> dict[str, Any] | None:
        for segment in (namespace, name):
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", segment):
                raise ValueError("invalid contract resource key")
        contract = resource == "continuitycontracts"
        api = f"/apis/{API_VERSION_VALUE}" if contract else "/api/v1"
        label = "ContinuityContract" if contract else resource
        path = f"{api}/namespaces/{namespace}/{resource}"
        if method != "POST":
            path += f"/{name}"
        if method == "PUT":
            path += "/status"
        headers = {"Accept": accept}
        body = None
        if payload is not None:
            body = json.dumps(payload, allow_nan=False).encode()
            headers["Content-Type"] = (
                "application/merge-patch+json"
                if method == "PATCH"
                else "application/json"
            )
        with closing(self.connect()) as connection:
            timeout = connection.timeout
            if (
                type(timeout) not in (float, int)
                or not math.isfinite(timeout)
                or timeout <= 0
            ):
                raise ValueError(
                    "ContinuityContract transport requires a finite positive socket timeout"
                )
            if connection.sock is not None:
                connection.sock.settimeout(timeout)
            connection.request(method, path, body=body, headers=headers)
            with connection.getresponse() as response:
                if response.status == (201 if method == "POST" else 200):
                    obj = _response_object(response)
                    if obj is None:
                        raise ValueError(f"{label} {method} returned an invalid object")
                    return obj
                if response.status == 409 and method in ("PUT", "PATCH"):
                    raise StatusConflict
                if response.status == 404 or (
                    response.status == 409 and method == "POST"
                ):
                    failure = _response_object(response) or {}
                    details = failure.get("details")
                    if (
                        isinstance(details, dict)
                        and details.get("group", "") == (API_GROUP if contract else "")
                        and details.get("name") == name
                        and (contract or details.get("kind") == resource)
                    ):
                        if (
                            response.status == 404
                            and failure.get("reason") == "NotFound"
                        ):
                            if method == "GET":
                                return None
                            if method == "PUT":
                                raise StatusConflict
                        if (
                            response.status == 409
                            and failure.get("reason") == "AlreadyExists"
                        ):
                            raise FileExistsError("binding ConfigMap already exists")
                raise RuntimeError(f"{label} {method} failed: HTTP {response.status}")
