"""Regression tests for hyops.runtime.redact.

Run with:
    python3 -m unittest hyops.runtime.tests.test_redact
"""

from __future__ import annotations

import unittest

from hyops.runtime.redact import redact, redact_text

REDACTED = "***REDACTED***"


class TestRedactSecretShapes(unittest.TestCase):
    """Each case pairs raw input containing a real-looking secret with the
    exact secret value, so the assertion proves the value is gone -- not
    just that *some* redaction happened somewhere in the string."""

    def _assert_redacted(self, raw: str, secret: str) -> str:
        out = redact(raw)
        self.assertNotIn(secret, out, f"secret leaked in output: {out!r}")
        self.assertIn(REDACTED, out, f"no redaction marker in output: {out!r}")
        return out

    # --- Authorization: Bearer ... -----------------------------------

    def test_authorization_bearer_header(self):
        raw = "Authorization: Bearer sk_live_abc123XYZ789"
        self._assert_redacted(raw, "sk_live_abc123XYZ789")

    def test_authorization_bearer_case_insensitive(self):
        raw = "authorization: bearer sk_live_abc123XYZ789"
        self._assert_redacted(raw, "sk_live_abc123XYZ789")

    def test_authorization_bearer_exact_output(self):
        raw = "Authorization: Bearer sk_live_abc123XYZ789"
        self.assertEqual(redact(raw), "Authorization: Bearer ***REDACTED***")

    # --- token= / access_token= (unquoted key=value or key: value) ----

    def test_token_equals(self):
        raw = "token=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_access_token_equals(self):
        raw = "access_token=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_refresh_token_colon(self):
        raw = "refresh_token: abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_id_token_equals(self):
        raw = "id_token=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_client_secret_equals_unquoted(self):
        raw = "client_secret=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    # --- JSON-style "client_secret": "..." -----------------------------

    def test_json_client_secret(self):
        raw = '{"client_secret": "abcdef1234567890"}'
        out = self._assert_redacted(raw, "abcdef1234567890")
        self.assertEqual(out, '{"client_secret": "***REDACTED***"}')

    def test_json_token(self):
        raw = '{"token": "abcdef1234567890"}'
        out = self._assert_redacted(raw, "abcdef1234567890")
        self.assertEqual(out, '{"token": "***REDACTED***"}')

    def test_json_access_token(self):
        raw = '{"access_token": "abcdef1234567890"}'
        self._assert_redacted(raw, "abcdef1234567890")

    # --- password= / passphrase= / secret= / api_key= / apikey= -------

    def test_password_equals(self):
        raw = "password=SuperSecretP@ss1"
        self._assert_redacted(raw, "SuperSecretP@ss1")

    def test_passphrase_colon(self):
        raw = "passphrase: correct-horse-battery-staple123"
        out = self._assert_redacted(raw, "correct-horse-battery-staple123")
        self.assertEqual(out, "passphrase: ***REDACTED***")

    def test_secret_equals(self):
        raw = "secret=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_api_key_equals(self):
        raw = "api_key=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_apikey_equals_no_underscore(self):
        raw = "apikey=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_secret_word_boundary_not_triggered_by_client_secret_alone(self):
        # client_secret is handled by the token-family pattern, not the
        # bare "secret" pattern; this just confirms it still gets redacted.
        raw = "client_secret=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    # --- environment-style cloud / GitHub tokens -----------------------

    def test_github_token_env(self):
        raw = "GITHUB_TOKEN=ghp_abcdef1234567890"
        self._assert_redacted(raw, "ghp_abcdef1234567890")

    def test_tfc_token_env(self):
        raw = "TFC_TOKEN=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_hcloud_token_env(self):
        raw = "HCLOUD_TOKEN=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    def test_aws_secret_access_key_env(self):
        raw = "AWS_SECRET_ACCESS_KEY=abcdEFGH1234567890"
        self._assert_redacted(raw, "abcdEFGH1234567890")

    def test_aws_session_token_env(self):
        raw = "AWS_SESSION_TOKEN=abcdEFGH1234567890"
        self._assert_redacted(raw, "abcdEFGH1234567890")

    def test_env_style_pattern_is_case_insensitive(self):
        # All default patterns are compiled with (?i), so the env-style
        # pattern itself matches lowercase github_token=... directly.
        # (The generic token= pattern can't match here regardless of case:
        # the underscore in github_token means there's no word boundary
        # before "token".)
        raw = "github_token=abcdef1234567890"
        self._assert_redacted(raw, "abcdef1234567890")

    # --- multiple secrets in one payload --------------------------------

    def test_multiple_secrets_in_one_log_line(self):
        raw = (
            "Authorization: Bearer sk_live_abc123 "
            "GITHUB_TOKEN=ghp_def456 "
            "password=hunter2"
        )
        out = redact(raw)
        for secret in ("sk_live_abc123", "ghp_def456", "hunter2"):
            self.assertNotIn(secret, out)
        self.assertEqual(out.count(REDACTED), 3)

    # --- benign text must pass through unchanged ------------------------

    def test_benign_log_line_unchanged(self):
        raw = "2026-07-11 12:00:00 INFO run started for source=orders-db"
        self.assertEqual(redact(raw), raw)

    def test_benign_text_mentioning_token_word_without_value(self):
        raw = "Refreshing the auth token before the next probe run."
        self.assertEqual(redact(raw), raw)

    def test_empty_string(self):
        self.assertEqual(redact(""), "")

    def test_redact_text_matches_redact(self):
        raw = "token=abcdef1234567890"
        self.assertEqual(redact(raw), redact_text(raw))


if __name__ == "__main__":
    unittest.main()