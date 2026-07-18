from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.drivers.iac.terragrunt.contracts.proxmox_vm import ProxmoxVmContract


class ProxmoxVmContractDeletionOnlyTests(unittest.TestCase):
    def _run_contract(
        self,
        *,
        existing: set[str],
        requested: set[str],
        allow_replace: bool,
    ) -> tuple[dict, list[str], str]:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            module_dir = (
                state_dir
                / "modules"
                / "platform__onprem__platform-vm"
                / "instances"
            )
            module_dir.mkdir(parents=True)
            (module_dir / "platform_vms.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "outputs": {
                            "vms": {name: {"vm_id": index + 100} for index, name in enumerate(sorted(existing))}
                        },
                    }
                ),
                encoding="utf-8",
            )
            inputs = {
                "template_vm_id": 107,
                "allow_vm_set_replace": allow_replace,
                "vms": {name: {} for name in sorted(requested)},
            }
            credentials = {
                "proxmox_url": "https://proxmox.invalid:8006/api2/json",
                "proxmox_token_id": "automation@pam!infra-token",
                "proxmox_token_secret": "test-only",
                "proxmox_node": "pve",
            }
            with patch(
                "hyops.drivers.iac.terragrunt.contracts.proxmox_vm._probe_proxmox_vm_exists",
                return_value=(False, False, ""),
            ):
                return ProxmoxVmContract().preprocess_inputs(
                    command_name="plan",
                    module_ref="platform/onprem/platform-vm",
                    inputs=inputs,
                    profile_policy={},
                    runtime={
                        "state_dir": str(state_dir),
                        "state_instance": "platform_vms",
                        "env": "shared",
                    },
                    env={"HYOPS_ENV": "shared"},
                    credential_env=credentials,
                )

    def test_missing_template_is_allowed_for_confirmed_strict_subset(self) -> None:
        _, warnings, error = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01"},
            allow_replace=True,
        )

        self.assertEqual(error, "")
        self.assertTrue(any("deletion-only VM-set shrink" in warning for warning in warnings))

    def test_missing_template_still_blocks_mixed_replacement(self) -> None:
        _, _, error = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01", "replacement-01"},
            allow_replace=True,
        )

        self.assertIn("no VM/template with that ID exists", error)

    def test_vm_set_shrink_still_requires_explicit_confirmation(self) -> None:
        _, _, error = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01"},
            allow_replace=False,
        )

        self.assertIn("allow_vm_set_replace=true", error)


if __name__ == "__main__":
    unittest.main()
