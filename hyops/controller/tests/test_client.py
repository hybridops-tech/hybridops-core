import json
import socket
import unittest
from copy import deepcopy
from http.client import HTTPConnection
from io import BytesIO
from unittest.mock import Mock, patch

from hyops.continuity.api import API_GROUP, API_KIND, RecoverySetSpec
from hyops.continuity.api.v1alpha1 import API_VERSION_VALUE
from hyops.controller.client import (
    DISPATCH_ANNOTATION,
    TERMINAL_ANNOTATION,
    TERMINAL_FINALIZER,
    ContractClient,
)
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

    def test_finalizer_patch_replaces_only_the_observed_metadata(self):
        foreign = "other.example/retain"
        stamp = "2026-11-28T12:00:00Z"
        for desired, observed, deleting in (
            (
                [foreign, TERMINAL_FINALIZER],
                {"finalizers": [TERMINAL_FINALIZER, foreign]},
                False,
            ),
            ([foreign], {"finalizers": [foreign], "deletionTimestamp": stamp}, True),
            ([], {"deletionTimestamp": stamp}, True),
        ):
            with self.subTest(desired=desired):
                obj = deepcopy(self.written)
                obj["metadata"].update(observed)
                client, conn = self.response(200, obj)
                client.replace_finalizers(
                    "default", "lab", "uid", "42", desired, deleting=deleting
                )
                request = conn.request.call_args
                self.assertEqual(
                    request.args,
                    (
                        "PATCH",
                        f"/apis/{API_VERSION_VALUE}/namespaces/default/continuitycontracts/lab",
                    ),
                )
                self.assertEqual(
                    request.kwargs["headers"]["Content-Type"],
                    "application/merge-patch+json",
                )
                self.assertEqual(
                    json.loads(request.kwargs["body"]),
                    {
                        "metadata": {
                            "uid": "uid",
                            "resourceVersion": "42",
                            "finalizers": desired,
                        }
                    },
                )

    def test_unconfirmed_finalizer_patch_is_not_success(self):
        desired = ["other.example/retain"]
        for delta in (
            {"name": "another"},
            {"namespace": "another"},
            {"uid": "replacement"},
            {"resourceVersion": ""},
            {"finalizers": []},
            {"finalizers": desired * 2},
            {"finalizers": [None]},
            {"deletionTimestamp": "2026-11-28T12:00:00Z"},
        ):
            with self.subTest(delta=delta):
                obj = deepcopy(self.written)
                obj["metadata"].update({"finalizers": desired, **delta})
                client, _ = self.response(200, obj)
                with self.assertRaisesRegex(
                    RuntimeError, "finalizer write was not confirmed"
                ):
                    client.replace_finalizers("default", "lab", "uid", "42", desired)
        client, _ = self.response(200, self.written)
        with self.assertRaisesRegex(RuntimeError, "finalizer write was not confirmed"):
            client.replace_finalizers("default", "lab", "uid", "42", [], deleting=True)
        for uid, version, names in (
            ("", "42", []),
            ("uid", "", []),
            ("uid", "42", None),
        ):
            client, conn = self.response(200, self.written)
            with self.assertRaises(ValueError):
                client.replace_finalizers("default", "lab", uid, version, names)
            conn.request.assert_not_called()

    def test_finalizer_conflict_or_disappearance_requires_a_new_read(self):
        details = {"group": API_GROUP, "kind": "continuitycontracts", "name": "lab"}
        for code, reason in ((409, "Conflict"), (404, "NotFound")):
            for target, expected in (
                (details, StatusConflict),
                ({**details, "name": "another"}, RuntimeError),
                ({**details, "kind": "namespaces"}, RuntimeError),
                ({}, RuntimeError),
            ):
                with self.subTest(code=code, target=target):
                    client, conn = self.response(
                        code, {"reason": reason, "details": target}
                    )
                    with self.assertRaises(expected):
                        client.replace_finalizers(
                            "default", "lab", "uid", "42", [], deleting=True
                        )
                    conn.request.assert_called_once()

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
            {"metadata": {**obj["metadata"], "ownerReferences": [{"uid": "parent"}]}},
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

    def test_dispatch_patch_is_scoped_to_the_observed_object(self):
        obj = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "immutable": True,
            "data": {"binding.json": "{}"},
            "metadata": {
                "namespace": "records",
                "name": "record",
                "uid": "binding-uid",
                "resourceVersion": "8",
                "annotations": {DISPATCH_ANNOTATION: "run-1"},
            },
        }
        args = ("records", "record", "binding-uid", "7", "run-1")
        client, conn = self.response(200, obj)
        client.mark_dispatch(*args)
        conn.request.assert_called_once()
        request = conn.request.call_args
        self.assertEqual(
            request.args, ("PATCH", "/api/v1/namespaces/records/configmaps/record")
        )
        self.assertEqual(
            request.kwargs["headers"]["Content-Type"], "application/merge-patch+json"
        )
        self.assertEqual(
            json.loads(request.kwargs["body"]),
            {
                "metadata": {
                    "uid": "binding-uid",
                    "resourceVersion": "7",
                    "annotations": {DISPATCH_ANNOTATION: "run-1"},
                },
            },
        )
        for metadata in (
            {"annotations": {}},
            {"annotations": {DISPATCH_ANNOTATION: "different"}},
            {"uid": "replacement"},
            {"name": "another"},
            {"deletionTimestamp": "2026-11-28T13:00:00Z"},
        ):
            with self.subTest(metadata=metadata):
                client, conn = self.response(
                    200, {**obj, "metadata": {**obj["metadata"], **metadata}}
                )
                with self.assertRaises((ValueError, RuntimeError)):
                    client.mark_dispatch(*args)
                conn.request.assert_called_once()

    def test_dispatch_conflict_is_not_retried(self):
        client, conn = self.response(409, {"reason": "Conflict"})
        with self.assertRaises(StatusConflict):
            client.mark_dispatch("records", "record", "binding-uid", "7", "run-1")
        conn.request.assert_called_once()

    def test_terminal_configmap_confirms_only_the_exact_text(self):
        content = '{"result":"é"}\n'
        cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "immutable": True,
            "metadata": {
                "name": "record",
                "namespace": "lab",
                "uid": "a",
                "resourceVersion": "4",
            },
            "data": {"terminal.json": content},
        }
        client, conn = self.response(201, cm)
        self.assertEqual(client.create_terminal_evidence("lab", "record", content), cm)
        self.assertEqual(
            json.loads(conn.request.call_args.kwargs["body"])["data"], cm["data"]
        )
        self.assertEqual(
            self.response(200, cm)[0].read_terminal_evidence("lab", "record"), cm
        )
        with self.assertRaises(RuntimeError):
            self.response(201, cm)[0].create_terminal_evidence(
                "lab", "record", content.rstrip()
            )
        for delta in (
            {"immutable": False},
            {"metadata": {**cm["metadata"], "ownerReferences": [{"uid": "parent"}]}},
            {"data": {"binding.json": content}},
            {"data": {**cm["data"], "extra": ""}},
            {"binaryData": {"more": "AA=="}},
            {
                "metadata": {
                    **cm["metadata"],
                    "deletionTimestamp": "2026-11-28T12:00:00Z",
                }
            },
        ):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.response(200, {**cm, **delta})[0].read_terminal_evidence(
                    "lab", "record"
                )

    def test_terminal_witness_pin_is_an_identity_guarded_binding_patch(self):
        cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "immutable": True,
            "metadata": {
                "name": "binding",
                "namespace": "records",
                "uid": "old",
                "resourceVersion": "10",
                "annotations": {TERMINAL_ANNOTATION: "witness-uid"},
            },
            "data": {"binding.json": "{}"},
        }
        args = ("records", "binding", "old", "9", "witness-uid")
        client, conn = self.response(200, cm)
        client.pin_terminal_witness(*args)
        self.assertEqual(
            conn.request.call_args.args,
            ("PATCH", "/api/v1/namespaces/records/configmaps/binding"),
        )
        self.assertEqual(
            json.loads(conn.request.call_args.kwargs["body"]),
            {
                "metadata": {
                    "uid": "old",
                    "resourceVersion": "9",
                    "annotations": {TERMINAL_ANNOTATION: "witness-uid"},
                }
            },
        )
        for meta in (
            {"uid": "new"},
            {"annotations": {}},
            {"annotations": {TERMINAL_ANNOTATION: "other"}},
        ):
            with self.subTest(meta=meta), self.assertRaises(RuntimeError):
                self.response(200, {**cm, "metadata": {**cm["metadata"], **meta}})[
                    0
                ].pin_terminal_witness(*args)
        with self.assertRaises(StatusConflict):
            self.response(409, {"reason": "Conflict"})[0].pin_terminal_witness(*args)

    def test_terminal_status_confirmation_uses_all_normalized_fields(self):
        digest = "sha256:" + "a" * 64
        sets = tuple(
            RecoverySetSpec(name, "capture", name, "recovery")
            for name in ("first", "next")
        )
        status = {
            "observedGeneration": 1,
            "phase": "Succeeded",
            "terminalEvidenceRef": {
                "kind": "ConfigMap",
                "name": "record",
                "digest": digest,
            },
            "recoverySets": [
                {
                    "name": s.name,
                    "evidence": s.evidence,
                    "role": s.role,
                    "digest": digest,
                }
                for s in sets
            ],
        }
        observed = {
            **status,
            "conditions": [],
            "terminalEvidenceRef": {
                **status["terminalEvidenceRef"],
                "apiGroup": "",
            },
            "recoverySets": status["recoverySets"][::-1],
        }
        args = ("default", "lab", "uid", "42", status)
        client, conn = self.response(200, {**self.written, "status": observed})
        client.replace_terminal_status(*args, recovery_sets=sets)
        self.assertEqual(
            conn.request.call_args.args,
            (
                "PUT",
                f"/apis/{API_VERSION_VALUE}/namespaces/default/continuitycontracts/lab/status",
            ),
        )
        self.assertEqual(
            json.loads(conn.request.call_args.kwargs["body"])["metadata"],
            {
                "name": "lab",
                "namespace": "default",
                "uid": "uid",
                "resourceVersion": "42",
            },
        )
        for delta in (
            {"observedGeneration": True},
            {"phase": "Failed"},
            {"terminalEvidenceRef": None},
            {"terminalEvidenceRef": {**status["terminalEvidenceRef"], "name": "other"}},
            {"conditions": self.status["conditions"]},
            {"recoverySets": []},
            {
                "recoverySets": [
                    {**s, "digest": "sha256:" + "b" * 64}
                    for s in status["recoverySets"]
                ]
            },
        ):
            with (
                self.subTest(delta=delta),
                self.assertRaisesRegex(RuntimeError, "was not confirmed"),
            ):
                client, _ = self.response(
                    200, {**self.written, "status": {**observed, **delta}}
                )
                client.replace_terminal_status(*args, recovery_sets=sets)
        client, conn = self.response(200, self.written)
        with self.assertRaises(ValueError):
            client.replace_terminal_status(*args[:-1], self.status)
        conn.request.assert_not_called()

    def test_terminal_status_accepts_deletion_only_when_requested(self):
        status = {
            "observedGeneration": 1,
            "phase": "Failed",
            "terminalEvidenceRef": {
                "kind": "ConfigMap",
                "name": "record",
                "digest": "sha256:" + "a" * 64,
            },
        }
        args = ("default", "lab", "uid", "42", status)
        for deleting, stamp in ((True, "2026-11-28T12:00:00Z"), (False, None)):
            obj = {
                **self.written,
                "metadata": {
                    **self.written["metadata"],
                    "deletionTimestamp": stamp,
                    "generation": 2 if deleting else 1,
                },
                "status": status,
            }
            client, _ = self.response(200, obj)
            client.replace_terminal_status(*args, deleting=deleting)
            client, _ = self.response(200, obj)
            with self.assertRaisesRegex(RuntimeError, "write was not confirmed"):
                client.replace_terminal_status(*args, deleting=not deleting)
            for generation in (1, 3) if deleting else (2,):
                obj["metadata"]["generation"] = generation
                client, _ = self.response(200, obj)
                with self.assertRaisesRegex(RuntimeError, "write was not confirmed"):
                    client.replace_terminal_status(*args, deleting=deleting)
