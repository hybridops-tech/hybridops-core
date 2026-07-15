"""Tests for Core release awareness."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hyops.update import checker


class UpdateCheckerTests(unittest.TestCase):
    def test_development_build_skips_network(self) -> None:
        with patch.object(checker, "__version__", "0.0.0-dev"), patch.object(
            checker.requests, "get"
        ) as request:
            status = checker.check_for_update()
        self.assertEqual(status.state, "development")
        request.assert_not_called()

    def test_reports_available_release_and_writes_cache(self) -> None:
        response = Mock()
        response.json.return_value = {
            "tag_name": "v1.3.0",
            "html_url": "https://example.test/releases/v1.3.0",
        }
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as directory, patch.object(
            checker, "__version__", "1.2.0"
        ), patch.object(checker.requests, "get", return_value=response):
            status = checker.check_for_update(root=directory, now=1000)
            cache = Path(directory) / "meta" / "core-update.json"
            data = json.loads(cache.read_text(encoding="utf-8"))
        self.assertEqual(status.state, "update_available")
        self.assertEqual(status.latest, "1.3.0")
        self.assertEqual(data["tag_name"], "v1.3.0")

    def test_uses_fresh_cache_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "meta" / "core-update.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(
                json.dumps({"checked_at": 900, "tag_name": "v1.2.0", "html_url": ""}),
                encoding="utf-8",
            )
            with patch.object(checker, "__version__", "1.2.0"), patch.object(
                checker.requests, "get"
            ) as request:
                status = checker.check_for_update(root=directory, now=1000)
        self.assertEqual(status.state, "current")
        self.assertTrue(status.cached)
        request.assert_not_called()

    def test_new_release_line_is_reported_as_unsupported(self) -> None:
        response = Mock()
        response.json.return_value = {"tag_name": "v0.2.0", "html_url": ""}
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as directory, patch.object(
            checker, "__version__", "0.1.9"
        ), patch.object(checker.requests, "get", return_value=response):
            status = checker.check_for_update(root=directory, use_cache=False)
        self.assertEqual(status.state, "unsupported")

    def test_network_failure_is_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            checker, "__version__", "1.2.0"
        ), patch.object(checker.requests, "get", side_effect=checker.requests.ConnectionError("down")):
            status = checker.check_for_update(root=directory, use_cache=False)
        self.assertEqual(status.state, "offline")


if __name__ == "__main__":
    unittest.main()
