"""Namespaced ContinuityContract reads and conditional status updates."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import closing
from http.client import HTTPConnection
from typing import Any

from hyops.continuity.api import API_GROUP, API_KIND
from hyops.continuity.api.v1alpha1 import API_VERSION_VALUE

from .reconcile import StatusConflict


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
        self._request(
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
            connection.request(method, path, body=body, headers=headers)
            with connection.getresponse() as response:
                if response.status == 200:
                    if method == "GET":
                        obj = json.load(response)
                        if not isinstance(obj, dict):
                            raise ValueError("expected a ContinuityContract object")
                        return obj
                    return None
                if response.status == 409 and method == "PUT":
                    raise StatusConflict
                if response.status == 404:
                    failure = json.load(response)
                    details = failure.get("details") or {}
                    if (
                        failure.get("reason") == "NotFound"
                        and details.get("group") == API_GROUP
                        and details.get("name") == name
                    ):
                        if method == "GET":
                            return None
                        raise StatusConflict
                raise RuntimeError(
                    f"ContinuityContract {method} failed: HTTP {response.status}"
                )
