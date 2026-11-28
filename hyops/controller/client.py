"""Namespaced ContinuityContract reads and conditional status updates."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from contextlib import closing
from http.client import HTTPConnection, HTTPResponse
from typing import Any

from hyops.continuity.api import API_GROUP, API_KIND
from hyops.continuity.api.v1alpha1 import API_VERSION_VALUE

from .reconcile import StatusConflict


def _response_object(response: HTTPResponse) -> dict[str, Any] | None:
    try:
        value = json.load(response)
    except ValueError:
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


class ContractClient:
    def __init__(self, connect: Callable[[], HTTPConnection]) -> None:
        self.connect = connect

    def read(self, namespace: str, name: str) -> dict[str, Any] | None:
        return self._request("GET", namespace, name)

    def replace_status(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        status: dict[str, Any],
    ) -> None:
        if not uid or not resource_version:
            raise ValueError("a status write requires UID and resourceVersion")
        expected = _validation_condition(status)
        if expected is None:
            raise ValueError(
                "expected one ContractValid condition for the observed generation"
            )
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
            and type(metadata.get("generation")) is int
            and metadata["generation"] == status["observedGeneration"]
            and isinstance(metadata.get("resourceVersion"), str)
            and metadata["resourceVersion"].strip()
            and isinstance(observed, dict)
            and observed.get("phase", "Pending") == status.get("phase", "Pending")
            and _validation_condition(observed) == expected
        ):
            raise RuntimeError("ContinuityContract status write was not confirmed")

    def _request(
        self,
        method: str,
        namespace: str,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        for segment in (namespace, name):
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", segment):
                raise ValueError("invalid contract resource key")
        path = f"/apis/{API_VERSION_VALUE}/namespaces/{namespace}/continuitycontracts/{name}"
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            path += "/status"
            body = json.dumps(payload, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
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
                if response.status == 200:
                    obj = _response_object(response)
                    if obj is None:
                        raise ValueError(
                            f"ContinuityContract {method} returned an invalid object"
                        )
                    return obj
                if response.status == 409 and method == "PUT":
                    raise StatusConflict
                if response.status == 404:
                    failure = _response_object(response) or {}
                    details = failure.get("details")
                    if (
                        failure.get("reason") == "NotFound"
                        and isinstance(details, dict)
                        and details.get("group") == API_GROUP
                        and details.get("name") == name
                    ):
                        if method == "GET":
                            return None
                        raise StatusConflict
                raise RuntimeError(
                    f"ContinuityContract {method} failed: HTTP {response.status}"
                )
