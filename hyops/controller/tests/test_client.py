import json
import unittest
from http.client import HTTPConnection
from io import BytesIO
from unittest.mock import Mock

from hyops.continuity.api import API_GROUP
from hyops.controller.client import ContractClient
from hyops.controller.reconcile import StatusConflict


class ContractClientTests(unittest.TestCase):
    def response(self, code, payload):
        conn = Mock(spec=HTTPConnection)
        response = BytesIO(json.dumps(payload).encode())
        response.status = code
        conn.getresponse.return_value = response
        return ContractClient(lambda: conn), conn

    def test_read_distinguishes_missing_contract_from_missing_api(self):
        missing = {"reason": "NotFound", "details": {"group": API_GROUP, "name": "lab"}}
        client, conn = self.response(404, missing)
        self.assertIsNone(client.read("default", "lab"))
        conn.close.assert_called_once()
        client, _ = self.response(404, {"reason": "NotFound"})
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            client.read("default", "lab")

    def test_auth_and_server_failures_are_not_conflicts(self):
        for code in (401, 403, 422, 503):
            with self.subTest(code=code):
                client, _ = self.response(code, {})
                with self.assertRaisesRegex(RuntimeError, f"HTTP {code}"):
                    client.replace_status("default", "lab", "uid", "42", {})

    def test_deleted_during_write_requires_a_new_read(self):
        client, _ = self.response(
            404, {"reason": "NotFound", "details": {"group": API_GROUP, "name": "lab"}}
        )
        with self.assertRaises(StatusConflict):
            client.replace_status("default", "lab", "uid", "42", {})

    def test_non_object_read_does_not_become_an_absent_contract(self):
        client, _ = self.response(200, None)
        with self.assertRaises(ValueError):
            client.read("default", "lab")

    def test_invalid_resource_key_never_makes_a_request(self):
        connect = Mock()
        for ns, name in (("..", "lab"), ("default", "lab/other"), ("", "lab")):
            with self.assertRaises(ValueError):
                ContractClient(connect).read(ns, name)
        connect.assert_not_called()
