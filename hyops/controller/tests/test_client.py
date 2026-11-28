import json
import socket
import unittest
from copy import deepcopy
from http.client import HTTPConnection
from io import BytesIO
from unittest.mock import Mock, patch

from hyops.continuity.api import API_GROUP, API_KIND
from hyops.continuity.api.v1alpha1 import API_VERSION_VALUE
from hyops.controller.client import ContractClient
from hyops.controller.reconcile import StatusConflict


class ContractClientTests(unittest.TestCase):
    def setUp(self):
        self.status = {
            "observedGeneration": 1,
            "conditions": [
                {
                    "type": "ContractValid",
                    "observedGeneration": 1,
                    "status": "False",
                    "reason": "UnknownField",
                    "message": "Contract specification is invalid.",
                    "lastTransitionTime": "2026-11-28T12:00:00Z",
                }
            ],
        }
        self.written = {
            "apiVersion": API_VERSION_VALUE,
            "kind": API_KIND,
            "metadata": {
                "name": "lab",
                "namespace": "default",
                "uid": "uid",
                "generation": 1,
                "resourceVersion": "43",
            },
            "spec": {"unknownField": True},
            "status": deepcopy(self.status),
        }

    def response(self, code, payload):
        conn = Mock(spec=HTTPConnection, timeout=10, sock=None)
        response = BytesIO(
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        response.status = code
        conn.getresponse.return_value = response
        return ContractClient(lambda: conn), conn

    def write(self, client):
        return client.replace_status("default", "lab", "uid", "42", self.status)

    def test_read_distinguishes_missing_contract_from_missing_api(self):
        missing = {"reason": "NotFound", "details": {"group": API_GROUP, "name": "lab"}}
        client, conn = self.response(404, missing)
        self.assertIsNone(client.read("default", "lab"))
        conn.close.assert_called_once()
        for failure in ({"reason": "NotFound"}, None, b"<html>untrusted</html>"):
            with self.subTest(failure=failure):
                client, _ = self.response(404, failure)
                with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                    client.read("default", "lab")

    def test_auth_and_server_failures_are_not_conflicts(self):
        for code in (401, 403, 422, 503):
            with self.subTest(code=code):
                client, _ = self.response(code, {})
                with self.assertRaisesRegex(RuntimeError, f"HTTP {code}"):
                    self.write(client)

    def test_deleted_during_write_requires_a_new_read(self):
        client, _ = self.response(
            404, {"reason": "NotFound", "details": {"group": API_GROUP, "name": "lab"}}
        )
        with self.assertRaises(StatusConflict):
            self.write(client)

    def test_acknowledges_owned_condition_without_decoding_invalid_spec(self):
        self.written["status"]["phase"] = "Pending"
        self.written["status"]["conditions"].insert(0, {"type": "InventoryReady"})
        client, conn = self.response(200, self.written)
        self.write(client)
        conn.request.assert_called_once()
        self.assertEqual(
            conn.request.call_args.args[:2],
            (
                "PUT",
                f"/apis/{API_VERSION_VALUE}/namespaces/default/continuitycontracts/lab/status",
            ),
        )

    def test_rejects_unconfirmed_status_write(self):
        for path, value in (
            (("apiVersion",), "v1"),
            (("kind",), "Status"),
            (("metadata", "uid"), "other"),
            (("metadata", "name"), "other"),
            (("metadata", "namespace"), "other"),
            (("metadata", "resourceVersion"), ""),
            (("metadata", "generation"), True),
            (("metadata", "generation"), 2),
            (("status", "observedGeneration"), True),
            (("status", "phase"), "Running"),
            (("status", "conditions"), []),
            (("status", "conditions"), self.status["conditions"] * 2),
            (("status", "conditions", 0, "observedGeneration"), True),
            (("status", "conditions", 0, "reason"), "UnexpectedReason"),
            (("status", "conditions", 0, "status"), "True"),
        ):
            with self.subTest(path=path, value=value):
                obj = deepcopy(self.written)
                parent = obj
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = value
                client, _ = self.response(200, obj)
                with self.assertRaisesRegex(RuntimeError, "write was not confirmed"):
                    self.write(client)
        client, _ = self.response(200, b"<html>untrusted</html>")
        with self.assertRaisesRegex(ValueError, "PUT returned an invalid object"):
            self.write(client)

    def test_refuses_unowned_status_before_writing(self):
        client, conn = self.response(200, self.written)
        for conditions in ([], self.status["conditions"] * 2):
            with self.assertRaisesRegex(ValueError, "expected one ContractValid"):
                client.replace_status(
                    "default",
                    "lab",
                    "uid",
                    "42",
                    {**self.status, "conditions": conditions},
                )
        conn.request.assert_not_called()

    def test_connection_timeout_must_be_finite_and_positive(self):
        for timeout in (
            HTTPConnection("unused").timeout,
            None,
            0,
            -1,
            True,
            float("inf"),
            float("nan"),
        ):
            with self.subTest(timeout=timeout):
                client, conn = self.response(200, {})
                conn.timeout = timeout
                with self.assertRaisesRegex(ValueError, "socket timeout"):
                    client.read("default", "lab")
                conn.request.assert_not_called()
                conn.close.assert_called_once()

    def test_idle_server_times_out_on_read_and_write(self):
        for method in ("GET", "PUT"):
            with self.subTest(method=method):
                left, right = socket.socketpair()
                with left, right:
                    # Keep the peer open without sending any HTTP response.
                    left.settimeout(2)
                    conn = HTTPConnection("unused", timeout=0.05)
                    conn.sock = left
                    client = ContractClient(lambda conn=conn: conn)
                    with self.assertRaises(TimeoutError):
                        if method == "GET":
                            client.read("default", "lab")
                        else:
                            self.write(client)
                    self.assertTrue(right.recv(1024).startswith(method.encode() + b" "))
                    self.assertEqual(left.gettimeout(), 0.05)

    def test_non_object_read_does_not_become_an_absent_contract(self):
        client, _ = self.response(200, None)
        with self.assertRaises(ValueError):
            client.read("default", "lab")

    @patch("hyops.controller.client._RESPONSE_LIMIT", 32)
    def test_oversize_success_and_not_found_bodies_fail_closed(self):
        for status in (200, 404):
            client, conn = self.response(status, b" " * 32 + b"{}")
            with self.assertRaisesRegex(ValueError, "exceeds the size limit"):
                client.read_reference("lab", "Secret", "access")
            conn.close.assert_called_once()

    def test_invalid_resource_key_never_makes_a_request(self):
        connect = Mock()
        for ns, name in (("..", "lab"), ("default", "lab/other"), ("", "lab")):
            with self.assertRaises(ValueError):
                ContractClient(connect).read(ns, name)
        connect.assert_not_called()

    def test_secret_read_negotiates_metadata_and_discards_sensitive_fields(self):
        identity = {
            "namespace": "lab",
            "name": "access",
            "uid": "uid",
            "resourceVersion": "1",
        }
        projection = {
            "apiVersion": "meta.k8s.io/v1",
            "kind": "PartialObjectMetadata",
            "metadata": {
                **identity,
                "annotations": {"last-applied": "sensitive"},
                "managedFields": [{"fieldsV1": {"sensitive": {}}}],
            },
        }
        client, conn = self.response(200, projection)
        self.assertEqual(
            client.read_reference("lab", "Secret", "access"),
            {**projection, "metadata": identity},
        )
        conn.request.assert_called_once_with(
            "GET",
            "/api/v1/namespaces/lab/secrets/access",
            body=None,
            headers={
                "Accept": "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"
            },
        )
        for response in (
            {**projection, "kind": "Secret", "apiVersion": "v1"},
            {**projection, "data": {"sensitive": "value"}},
            {**projection, "metadata": {**identity, "uid": {"sensitive": "value"}}},
        ):
            with self.subTest(response=response):
                client, conn = self.response(200, response)
                with self.assertRaisesRegex(
                    ValueError, "^invalid Secret metadata response$"
                ):
                    client.read_reference("lab", "Secret", "access")
                conn.request.assert_called_once()
        client, conn = self.response(406, {"message": "sensitive"})
        with self.assertRaisesRegex(RuntimeError, "^secrets GET failed: HTTP 406$"):
            client.read_reference("lab", "Secret", "access")
        conn.request.assert_called_once()

    def test_reference_reads_require_named_core_resource(self):
        obj = {"apiVersion": "v1", "kind": "ConfigMap", "data": {"file": "config"}}
        client, conn = self.response(200, obj)
        self.assertEqual(client.read_reference("lab", "ConfigMap", "inputs"), obj)
        self.assertEqual(
            conn.request.call_args.args,
            ("GET", "/api/v1/namespaces/lab/configmaps/inputs"),
        )
        missing = {
            "reason": "NotFound",
            "details": {"kind": "configmaps", "name": "inputs"},
        }
        client, _ = self.response(404, missing)
        self.assertIsNone(client.read_reference("lab", "ConfigMap", "inputs"))
        self.assertIsNone(self.response(404, missing)[0].read_binding("lab", "inputs"))
        for delta in ({"name": "other"}, {"group": API_GROUP}, {"kind": "namespaces"}):
            client, _ = self.response(
                404, {**missing, "details": {**missing["details"], **delta}}
            )
            with self.assertRaisesRegex(RuntimeError, "HTTP 404$"):
                client.read_reference("lab", "ConfigMap", "inputs")
        client, _ = self.response(200, {**obj, "kind": "Secret"})
        with self.assertRaisesRegex(ValueError, "^invalid ConfigMap response$"):
            client.read_reference("lab", "ConfigMap", "inputs")
        client, conn = self.response(200, obj)
        with self.assertRaises(ValueError):
            client.read_reference("lab", "Pod", "inputs")
        conn.request.assert_not_called()

    def test_create_requires_persisted_immutable_binding(self):
        record = {"z": "é", "a": 1}
        obj = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "immutable": True,
            "data": {"binding.json": '{"a":1,"z":"é"}'},
            "metadata": {
                "namespace": "controller",
                "name": "record",
                "uid": "binding-uid",
                "resourceVersion": "7",
            },
        }
        client, conn = self.response(201, obj)
        self.assertEqual(client.create_binding("controller", "record", record), obj)
        request = conn.request.call_args
        self.assertEqual(
            request.args, ("POST", "/api/v1/namespaces/controller/configmaps")
        )
        self.assertEqual(
            json.loads(request.kwargs["body"]),
            {**obj, "metadata": {"namespace": "controller", "name": "record"}},
        )
        self.assertEqual(
            self.response(200, obj)[0].read_binding("controller", "record"), obj
        )
        for overrides in (
            {"kind": "Secret"},
            {"immutable": 1},
            {"data": {"binding.json": "{}"}},
            {"binaryData": {"hidden": "eA=="}},
            {"metadata": {**obj["metadata"], "uid": ""}},
            {"metadata": {**obj["metadata"], "resourceVersion": None}},
            {"metadata": {**obj["metadata"], "name": "other"}},
            {"metadata": {**obj["metadata"], "namespace": "other"}},
            {
                "metadata": {
                    **obj["metadata"],
                    "deletionTimestamp": "2026-11-28T12:00:00Z",
                }
            },
        ):
            with self.subTest(overrides=overrides):
                client, conn = self.response(201, {**obj, **overrides})
                with self.assertRaises((ValueError, RuntimeError)):
                    client.create_binding("controller", "record", record)
                conn.request.assert_called_once()

    def test_only_named_already_exists_is_a_binding_conflict(self):
        failure = {
            "reason": "AlreadyExists",
            "details": {"name": "record", "kind": "configmaps"},
        }
        client, conn = self.response(409, failure)
        with self.assertRaises(FileExistsError):
            client.create_binding("controller", "record", {})
        conn.request.assert_called_once()
        for status, overrides in (
            (409, {"reason": "Conflict"}),
            (409, {"details": {"name": "other", "kind": "configmaps"}}),
            (403, {}),
            (404, {"reason": "NotFound"}),
            (200, {}),
        ):
            with self.subTest(status=status, overrides=overrides):
                client, conn = self.response(status, {**failure, **overrides})
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}$"):
                    client.create_binding("controller", "record", {})
                conn.request.assert_called_once()
