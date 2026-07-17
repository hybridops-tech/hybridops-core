from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hyops.vault.recovery import (
    _blueprint_details,
    _other_environment_vaults,
    _password_store_files,
    _secret_key_fingerprints,
)


class VaultRecoveryTests(unittest.TestCase):
    def test_eve_ng_blueprint_credentials_are_declared(self):
        payload, keys = _blueprint_details(
            SimpleNamespace(
                ref="gcp/eve-ng@v1",
                blueprints_root="blueprints",
                modules_root="modules",
            )
        )

        self.assertEqual(payload["blueprint_ref"], "gcp/eve-ng@v1")
        self.assertEqual(keys, ["EVENG_ROOT_PASSWORD", "EVENG_ADMIN_PASSWORD"])

    def test_password_store_inventory_ignores_git_metadata(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            (store / ".gpg-id").write_text("fingerprint\n", encoding="utf-8")
            entry = store / "hybridops" / "ansible-vault.gpg"
            entry.parent.mkdir()
            entry.write_bytes(b"encrypted")
            git_config = store / ".git" / "config"
            git_config.parent.mkdir()
            git_config.write_text("[core]\n", encoding="utf-8")

            self.assertEqual(
                _password_store_files(store),
                [".gpg-id", "hybridops/ansible-vault.gpg"],
            )

    @patch("hyops.vault.recovery.subprocess.run")
    def test_primary_secret_key_fingerprints_exclude_subkeys(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "\n".join(
            [
                "sec:u:255:22:KEY1:0:0:::::scESC:::+::ed25519:::0:",
                "fpr:::::::::PRIMARY1:",
                "uid:u::::0::HASH::HybridOps Vault (local)::::::::::0:",
                "ssb:u:255:18:SUB1:0:0:::::e:::+::cv25519::",
                "fpr:::::::::SUBKEY1:",
                "sec:u:255:22:KEY2:0:0:::::scESC:::+::ed25519:::0:",
                "fpr:::::::::PRIMARY2:",
            ]
        )

        self.assertEqual(_secret_key_fingerprints(), ["PRIMARY1", "PRIMARY2"])

    def test_other_environment_vaults_are_detected(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            selected = home / ".hybridops/envs/dev/vault/bootstrap.vault.env"
            other = home / ".hybridops/envs/test/vault/bootstrap.vault.env"
            selected.parent.mkdir(parents=True)
            other.parent.mkdir(parents=True)
            selected.write_bytes(b"selected")
            other.write_bytes(b"other")

            with patch("hyops.vault.recovery.Path.home", return_value=home):
                self.assertEqual(_other_environment_vaults(selected), [other.resolve()])


if __name__ == "__main__":
    unittest.main()
