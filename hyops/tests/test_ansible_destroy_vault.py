"""Tests for lifecycle-aware Ansible vault loading."""

from unittest import TestCase

from hyops.drivers.config.ansible.driver import _should_load_vault_env


class AnsibleDestroyVaultTests(TestCase):
    def test_destroy_skips_optional_vault_loading(self) -> None:
        self.assertFalse(
            _should_load_vault_env(
                load_vault_env=True,
                effective_lifecycle="destroy",
                missing_before_vault=[],
            )
        )

    def test_destroy_loads_missing_declared_values(self) -> None:
        self.assertTrue(
            _should_load_vault_env(
                load_vault_env=True,
                effective_lifecycle="destroy",
                missing_before_vault=["DESTROY_TOKEN"],
            )
        )

    def test_apply_keeps_optional_vault_loading(self) -> None:
        self.assertTrue(
            _should_load_vault_env(
                load_vault_env=True,
                effective_lifecycle="apply",
                missing_before_vault=[],
            )
        )
