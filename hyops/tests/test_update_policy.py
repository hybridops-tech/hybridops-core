"""Tests for the Core support policy."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from hyops.update import policy


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


class UpdatePolicyTests(unittest.TestCase):
    def test_default_policy_uses_packaging_metadata_path(self) -> None:
        self.assertEqual(
            policy.DEFAULT_POLICY_URL,
            "https://raw.githubusercontent.com/hybridops-tech/hybridops-core/main/"
            "pkg/support-policy.json",
        )

    def _response(self, minimum: str, enforce_after: str) -> Mock:
        response = Mock()
        response.json.return_value = {
            "schema_version": 1,
            "minimum_supported_version": minimum,
            "enforce_after": enforce_after,
        }
        response.raise_for_status.return_value = None
        return response

    def test_supported_release_is_allowed(self) -> None:
        response = self._response("0.1.2", "2026-08-01T00:00:00Z")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            policy, "__version__", "0.1.2"
        ), patch.object(policy.requests, "get", return_value=response):
            decision = policy.support_decision(root=directory, now=_timestamp("2026-08-02T00:00:00Z"))
        self.assertEqual(decision.state, "supported")

    def test_old_release_enters_grace_then_blocks(self) -> None:
        response = self._response("0.1.3", "2026-08-01T00:00:00Z")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            policy, "__version__", "0.1.2"
        ), patch.object(policy.requests, "get", return_value=response):
            grace = policy.support_decision(root=directory, now=_timestamp("2026-07-20T00:00:00Z"))
            blocked = policy.support_decision(root=directory, now=_timestamp("2026-08-02T00:00:00Z"))
        self.assertEqual(grace.state, "grace")
        self.assertEqual(blocked.state, "blocked")

    def test_stale_policy_is_used_when_service_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "meta" / "core-support-policy.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "minimum_supported_version": "0.1.3",
                        "enforce_after": "2026-08-01T00:00:00Z",
                        "checked_at": 1,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(policy, "__version__", "0.1.2"), patch.object(
                policy.requests, "get", side_effect=policy.requests.ConnectionError("offline")
            ):
                decision = policy.support_decision(
                    root=directory, now=_timestamp("2026-08-02T00:00:00Z")
                )
        self.assertTrue(decision.cached)
        self.assertEqual(decision.state, "blocked")

    def test_only_mutating_operations_are_gated(self) -> None:
        self.assertTrue(policy.command_requires_supported_release(Namespace(cmd="apply")))
        self.assertTrue(
            policy.command_requires_supported_release(
                Namespace(cmd="blueprint", blueprint_cmd="deploy", execute=True)
            )
        )
        self.assertFalse(policy.command_requires_supported_release(Namespace(cmd="destroy")))
        self.assertFalse(
            policy.command_requires_supported_release(
                Namespace(cmd="blueprint", blueprint_cmd="destroy", execute=True)
            )
        )
        self.assertFalse(policy.command_requires_supported_release(Namespace(cmd="show")))


if __name__ == "__main__":
    unittest.main()
