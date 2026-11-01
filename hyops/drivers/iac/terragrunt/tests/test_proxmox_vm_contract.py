from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.drivers.iac.terragrunt.contracts.proxmox_vm import (
    ProxmoxVmContract,
    _collect_windows_ipam_interfaces,
    _collect_windows_non_dhcp_interfaces,
)
from hyops.validators.platform.onprem._proxmox_vm import validate_vm_pool_inputs


class ProxmoxVmContractDeletionOnlyTests(unittest.TestCase):
    def _run_contract(
        self,
        *,
        existing: set[str],
        requested: set[str],
        allow_replace: bool,
        preserve_existing_vms: bool = False,
        preserve_existing_resources: bool = False,
        state_status: str = "ok",
    ) -> tuple[dict, list[str], str, int]:
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
                        "status": state_status,
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
                "preserve_existing_vms": preserve_existing_vms,
                "preserve_existing_resources": preserve_existing_resources,
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
            ) as probe:
                result = ProxmoxVmContract().preprocess_inputs(
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
                return (*result, probe.call_count)

    def test_missing_template_is_allowed_for_confirmed_strict_subset(self) -> None:
        _, warnings, error, _ = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01"},
            allow_replace=True,
        )

        self.assertEqual(error, "")
        self.assertTrue(any("deletion-only VM-set shrink" in warning for warning in warnings))

    def test_missing_template_still_blocks_mixed_replacement(self) -> None:
        _, _, error, _ = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01", "replacement-01"},
            allow_replace=True,
        )

        self.assertIn("no VM/template with that ID exists", error)

    def test_vm_set_shrink_still_requires_explicit_confirmation(self) -> None:
        _, _, error, _ = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01"},
            allow_replace=False,
        )

        self.assertIn("allow_vm_set_replace=true", error)

    def test_missing_template_is_allowed_for_explicit_stable_vm_update(self) -> None:
        _, warnings, error, probe_calls = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01", "pgcore-01"},
            allow_replace=False,
            preserve_existing_vms=True,
        )

        self.assertEqual(error, "")
        self.assertTrue(any("update-only run" in warning for warning in warnings))
        self.assertEqual(probe_calls, 1)

    def test_stable_update_flag_does_not_allow_new_vm_names(self) -> None:
        _, _, error, probe_calls = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01", "replacement-01"},
            allow_replace=False,
            preserve_existing_vms=True,
        )

        self.assertIn("requires the requested VM names to exactly match", error)
        self.assertEqual(probe_calls, 0)

    def test_preservation_requires_existing_state_ownership(self) -> None:
        _, _, error, probe_calls = self._run_contract(
            existing=set(),
            requested={"netbox-01"},
            allow_replace=False,
            preserve_existing_vms=True,
            preserve_existing_resources=True,
        )

        self.assertIn("non-empty managed VM set", error)
        self.assertEqual(probe_calls, 0)

    def test_preservation_requires_requested_vm_names(self) -> None:
        _, _, error, probe_calls = self._run_contract(
            existing={"netbox-01"},
            requested=set(),
            allow_replace=False,
            preserve_existing_vms=True,
            preserve_existing_resources=True,
        )

        self.assertIn("requires the requested VM names to exactly match", error)
        self.assertEqual(probe_calls, 0)

    def test_resource_preservation_requires_vm_set_preservation(self) -> None:
        _, _, error, probe_calls = self._run_contract(
            existing={"netbox-01"},
            requested={"netbox-01"},
            allow_replace=False,
            preserve_existing_resources=True,
        )

        self.assertIn("preserve_existing_resources=true requires", error)
        self.assertEqual(probe_calls, 0)

    def test_exact_preservation_skips_retired_template_probe(self) -> None:
        _, warnings, error, probe_calls = self._run_contract(
            existing={"netbox-01", "pgcore-01"},
            requested={"netbox-01", "pgcore-01"},
            allow_replace=False,
            preserve_existing_vms=True,
            preserve_existing_resources=True,
        )

        self.assertEqual(error, "")
        self.assertEqual(probe_calls, 0)
        self.assertTrue(any("provider-side resource provenance" in warning for warning in warnings))

    def test_error_and_running_state_retain_vm_ownership(self) -> None:
        for state_status in ("error", "running"):
            with self.subTest(state_status=state_status):
                _, _, error, probe_calls = self._run_contract(
                    existing={"netbox-01"},
                    requested={"netbox-01"},
                    allow_replace=False,
                    preserve_existing_vms=True,
                    preserve_existing_resources=True,
                    state_status=state_status,
                )

                self.assertEqual(error, "")
                self.assertEqual(probe_calls, 0)

    @staticmethod
    def _valid_vm_pool_inputs() -> dict:
        return {
            "require_ipam": False,
            "template_vm_id": 107,
            "cpu_cores": 2,
            "memory_mb": 4096,
            "disk_size_gb": 32,
            "cpu_type": "host",
            "os_type": "l26",
            "dns_domain": "example.test",
            "dns_servers": ["192.0.2.53"],
            "tags": ["platform"],
            "vms": {
                "netbox-01": {
                    "interfaces": [{"bridge": "vmbr0", "ipv4": {"address": "dhcp"}}]
                }
            },
        }

    def test_validator_requires_boolean_resource_preservation(self) -> None:
        inputs = self._valid_vm_pool_inputs()
        inputs["preserve_existing_resources"] = "true"

        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            validate_vm_pool_inputs(inputs)

    def test_validator_requires_vm_set_preservation_for_resources(self) -> None:
        inputs = self._valid_vm_pool_inputs()
        inputs["preserve_existing_resources"] = True

        with self.assertRaisesRegex(ValueError, "requires inputs.preserve_existing_vms=true"):
            validate_vm_pool_inputs(inputs)

    def test_windows_allows_multiple_dhcp_interfaces(self) -> None:
        inputs = {
            "os_type": "win10",
            "vms": {
                "win-01": {
                    "interfaces": [
                        {"bridge": "vnetmgmt", "ipv4": {"address": "dhcp"}},
                        {"bridge": "vnetdata"},
                    ]
                }
            },
        }

        self.assertEqual(_collect_windows_non_dhcp_interfaces(inputs), [])

    def test_windows_rejects_static_or_ipam_interface_without_guest_initializer(self) -> None:
        inputs = {
            "os_type": "win2022",
            "vms": {
                "win-01": {
                    "interfaces": [
                        {"bridge": "vnetmgmt", "ipv4": {"address": "dhcp"}},
                        {"bridge": "vnetdata", "ipv4": {"address": "10.20.0.25/24"}},
                    ]
                }
            },
        }

        affected = _collect_windows_non_dhcp_interfaces(inputs)
        self.assertEqual(
            affected,
            ["win-01/interfaces[2] (vnetdata, address=10.20.0.25/24)"],
        )

    def test_windows_allows_non_dhcp_interfaces_with_explicit_config_drive_opt_in(self) -> None:
        inputs = {
            "os_type": "win2022",
            "windows_config_drive": True,
            "vms": {
                "win-01": {
                    "interfaces": [
                        {"bridge": "vnetmgmt", "ipv4": {"address": "dhcp"}},
                        {"bridge": "vnetdata", "ipv4": {"address": "10.20.0.25/24"}},
                    ]
                }
            },
        }

        self.assertEqual(_collect_windows_non_dhcp_interfaces(inputs), [])

    def test_windows_rejects_omitted_ipam_interface_before_hydration(self) -> None:
        inputs = {
            "os_type": "win2022",
            "addressing": {"mode": "ipam", "ipam": {"provider": "netbox"}},
            "vms": {
                "win-01": {
                    "interfaces": [
                        {"bridge": "vnetmgmt", "ipv4": {"address": "dhcp"}},
                        {"bridge": "vnetdata"},
                    ]
                }
            },
        }

        self.assertEqual(
            _collect_windows_ipam_interfaces(inputs),
            ["win-01/interfaces[2] (vnetdata, NetBox IPAM address)"],
        )

    def test_windows_allows_omitted_ipam_interface_with_explicit_config_drive_opt_in(self) -> None:
        inputs = {
            "os_type": "win2022",
            "windows_config_drive": True,
            "addressing": {"mode": "ipam", "ipam": {"provider": "netbox"}},
            "vms": {"win-01": {"interfaces": [{"bridge": "vnetdata"}]}},
        }

        self.assertEqual(_collect_windows_ipam_interfaces(inputs), [])

    def test_contract_preflight_stops_windows_static_interface_before_external_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, error = ProxmoxVmContract().preprocess_inputs(
                command_name="plan",
                module_ref="platform/onprem/platform-vm",
                inputs={
                    "os_type": "win2022",
                    "vms": {
                        "win-01": {
                            "interfaces": [
                                {"bridge": "vnetmgmt", "ipv4": {"address": "10.10.0.25/24"}}
                            ]
                        }
                    },
                },
                profile_policy={},
                runtime={"state_dir": str(Path(tmp) / "state"), "env": "dev"},
                env={"HYOPS_ENV": "dev"},
                credential_env={},
            )

        self.assertIn("Windows guest networking currently supports DHCP interfaces only", error)

    def test_contract_preflight_stops_windows_ipam_interface_before_hydration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, error = ProxmoxVmContract().preprocess_inputs(
                command_name="plan",
                module_ref="platform/onprem/platform-vm",
                inputs={
                    "os_type": "win2022",
                    "addressing": {"mode": "ipam", "ipam": {"provider": "netbox"}},
                    "vms": {
                        "win-01": {
                            "interfaces": [
                                {"bridge": "vnetmgmt", "ipv4": {"address": "dhcp"}},
                                {"bridge": "vnetdata"},
                            ]
                        }
                    },
                },
                profile_policy={},
                runtime={"state_dir": str(Path(tmp) / "state"), "env": "dev"},
                env={"HYOPS_ENV": "dev"},
                credential_env={},
            )

        self.assertIn("an omitted address in IPAM mode would be hydrated", error)

if __name__ == "__main__":
    unittest.main()
