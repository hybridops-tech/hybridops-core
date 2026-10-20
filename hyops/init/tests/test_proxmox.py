import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.init.targets.proxmox import (
    _remote_token_controls,
    _rollback_created_remote_credentials,
    _validate_vault_persistence,
)
from hyops.runtime.vault import VaultAuth


class ProxmoxTokenRotationTest(unittest.TestCase):
    def _run_remote_bootstrap(
        self,
        *,
        user_exists: bool = False,
        token_exists: bool = False,
        snippets_ready: bool = True,
        bridge_ready: bool = True,
        acl_fail_match: str = "",
        mutation_fail_match: str = "",
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        script = (
            Path(__file__).parents[2]
            / "assets"
            / "init"
            / "proxmox"
            / "bootstrap-proxmox-remote.sh"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mutation_log = tmp_path / "mutations.log"
            fake_pveum = tmp_path / "pveum"
            fake_pveum.write_text(
                """#!/usr/bin/env bash
set -eu
if [[ "$*" == *"user list"* ]]; then
  [[ "${FAKE_USER_EXISTS:-0}" == "1" ]] && printf '%s\n' '[{"userid":"automation@pam"}]' || printf '%s\n' '[]'
elif [[ "$*" == *"user token list"* ]]; then
  [[ "${FAKE_TOKEN_EXISTS:-0}" == "1" ]] && printf '%s\n' '[{"tokenid":"infra-token"}]' || printf '%s\n' '[]'
elif [[ "$*" == *"user token add"* ]]; then
  printf '%s\n' "$*" >>"$MUTATION_LOG"
  printf '%s\n' '{"value":"test-secret"}'
elif [[ "$*" == *"acl modify"* ]]; then
  printf '%s\n' "$*" >>"$MUTATION_LOG"
  [[ -z "${ACL_FAIL_MATCH:-}" || "$*" != *"$ACL_FAIL_MATCH"* ]]
elif [[ "$*" == *"user add"* || "$*" == *"user token remove"* || "$*" == *"user delete"* ]]; then
  printf '%s\n' "$*" >>"$MUTATION_LOG"
  [[ -z "${MUTATION_FAIL_MATCH:-}" || "$*" != *"$MUTATION_FAIL_MATCH"* ]]
else
  exit 99
fi
""",
                encoding="utf-8",
            )
            fake_pveum.chmod(0o755)

            fake_pvesh = tmp_path / "pvesh"
            fake_pvesh.write_text(
                """#!/usr/bin/env bash
set -eu
if [[ "$*" == "get /storage --output-format json" ]]; then
  printf '%s\n' '[{"storage":"local-lvm"},{"storage":"local"}]'
elif [[ "$*" == *"/storage/local-lvm"* ]]; then
  printf '%s\n' '{"content":"images"}'
elif [[ "$*" == *"/storage/local"* ]]; then
  if [[ "${SNIPPETS_READY:-1}" == "1" ]]; then
    printf '%s\n' '{"content":"iso,snippets"}'
  else
    printf '%s\n' '{"content":"iso"}'
  fi
else
  exit 99
fi
""",
                encoding="utf-8",
            )
            fake_pvesh.chmod(0o755)

            fake_ip = tmp_path / "ip"
            fake_ip.write_text(
                """#!/usr/bin/env bash
if [[ "$*" == "link show vmbr0" ]]; then
  if [[ "${BRIDGE_READY:-1}" == "1" ]]; then
    printf '%s\n' '2: vmbr0: <BROADCAST,UP> state UP'
  else
    exit 1
  fi
else
  exit 99
fi
""",
                encoding="utf-8",
            )
            fake_ip.chmod(0o755)

            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{tmp}:{env['PATH']}",
                    "USER_FQ": "automation@pam",
                    "TOKEN_NAME": "infra-token",
                    "API_IP": "192.0.2.10",
                    "FAKE_USER_EXISTS": "1" if user_exists else "0",
                    "FAKE_TOKEN_EXISTS": "1" if token_exists else "0",
                    "SNIPPETS_READY": "1" if snippets_ready else "0",
                    "BRIDGE_READY": "1" if bridge_ready else "0",
                    "ACL_FAIL_MATCH": acl_fail_match,
                    "MUTATION_FAIL_MATCH": mutation_fail_match,
                    "MUTATION_LOG": str(mutation_log),
                }
            )
            env.update(extra_env or {})
            result = subprocess.run(
                ["bash", str(script)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            mutations = mutation_log.read_text(encoding="utf-8").splitlines() if mutation_log.exists() else []
            return result, mutations

    def test_known_secret_reuses_token(self):
        self.assertEqual(
            _remote_token_controls(token_secret="known", force=False),
            ["SKIP_TOKEN_GEN=1"],
        )

    def test_force_explicitly_allows_rotation(self):
        self.assertEqual(
            _remote_token_controls(token_secret="", force=True),
            ["ALLOW_TOKEN_ROTATION=1"],
        )

    def test_unknown_existing_token_is_not_rotated(self):
        result, mutations = self._run_remote_bootstrap(
            user_exists=True,
            token_exists=True,
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("rotation was not authorised", result.stderr)
        self.assertNotIn("Rotating token", result.stderr)
        self.assertEqual(mutations, [])

    def test_storage_failure_precedes_credential_mutation(self):
        result, mutations = self._run_remote_bootstrap(snippets_ready=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not support 'snippets' content", result.stderr)
        self.assertEqual(mutations, [])

    def test_bridge_failure_precedes_credential_mutation(self):
        result, mutations = self._run_remote_bootstrap(bridge_ready=False)

        self.assertEqual(result.returncode, 1)
        self.assertIn("bridge 'vmbr0' does not exist", result.stderr)
        self.assertEqual(mutations, [])

    def test_acl_failure_removes_new_credentials(self):
        result, mutations = self._run_remote_bootstrap(acl_fail_match="/vms")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to set ACL on /vms", result.stderr)
        self.assertTrue(any("user add automation@pam" in line for line in mutations))
        self.assertTrue(any("user token add automation@pam infra-token" in line for line in mutations))
        self.assertTrue(any("user token remove automation@pam infra-token" in line for line in mutations))
        self.assertTrue(any("user delete automation@pam" in line for line in mutations))

    def test_cleanup_failure_is_reported(self):
        result, _mutations = self._run_remote_bootstrap(
            acl_fail_match="/vms",
            mutation_fail_match="user token remove",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to remove token automation@pam!infra-token during rollback", result.stderr)

    def test_existing_token_is_reused_with_stored_secret(self):
        result, mutations = self._run_remote_bootstrap(
            user_exists=True,
            token_exists=True,
            extra_env={"SKIP_TOKEN_GEN": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reusing existing vault secret", result.stderr)
        self.assertFalse(any("user token add" in line for line in mutations))
        self.assertFalse(any("user token remove" in line for line in mutations))

    def test_successful_bootstrap_keeps_new_credentials(self):
        result, mutations = self._run_remote_bootstrap()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EXPORT:TOKEN_SECRET=test-secret", result.stdout)
        self.assertFalse(any("token remove" in line for line in mutations))
        self.assertFalse(any("user delete" in line for line in mutations))

    @patch("hyops.init.targets.proxmox.write_env")
    def test_vault_persistence_probe_removes_temporary_vault(self, write_env_mock):
        with tempfile.TemporaryDirectory() as tmp:
            vault_path = Path(tmp) / "bootstrap.vault.env"
            error = _validate_vault_persistence(vault_path, VaultAuth(password_file="unused"))

            self.assertEqual(error, "")
            probe_path = write_env_mock.call_args.args[0]
            self.assertEqual(probe_path.parent, vault_path.parent)
            self.assertFalse(probe_path.exists())

    @patch(
        "hyops.init.targets.proxmox.write_env",
        side_effect=RuntimeError("vault password command failed"),
    )
    def test_vault_persistence_probe_reports_failure(self, _write_env_mock):
        with tempfile.TemporaryDirectory() as tmp:
            error = _validate_vault_persistence(
                Path(tmp) / "bootstrap.vault.env",
                VaultAuth(password_file="unused"),
            )

        self.assertEqual(error, "vault password command failed")

    @patch(
        "hyops.init.targets.proxmox.run_capture_sensitive",
        return_value=SimpleNamespace(rc=0),
    )
    def test_local_vault_failure_rolls_back_created_remote_credentials(self, run_mock):
        error = _rollback_created_remote_credentials(
            values={
                "host": "192.0.2.10",
                "user_fq": "automation@pam",
                "token_name": "infra-token",
            },
            ssh_username="root",
            ssh_opts=["-o", "BatchMode=yes"],
            evidence_dir=Path("/tmp/evidence"),
            user_created=True,
            token_created=True,
        )

        self.assertEqual(error, "")
        command = run_mock.call_args.args[0][-1]
        self.assertIn("pveum user token remove automation@pam infra-token", command)
        self.assertIn("pveum user delete automation@pam", command)


if __name__ == "__main__":
    unittest.main()
