"""Test that all production modules have validators registered."""

from __future__ import annotations

import unittest
from hyops.validators.builtin.register import register_all
from hyops.validators.registry import _REGISTRY, validate_module_inputs, ModuleValidationError


class TestValidatorRegistrationCompleteness(unittest.TestCase):
    """Verify all production modules have validators and unknown keys are rejected."""

    @classmethod
    def setUpClass(cls) -> None:
        register_all()

    def test_all_production_modules_have_validators(self) -> None:
        """All production modules must have registered validators."""
        production_modules = [
            "core/azure/nat-gateway",
            "core/azure/resource-group",
            "core/azure/vnet",
            "core/hetzner/vyos-image-register",
            "core/hetzner/vyos-image-seed",
            "core/local/quickstart",
            "core/onprem/network-sdn",
            "core/onprem/template-image",
            "core/onprem/vyos-template-import",
            "core/onprem/vyos-template-seed",
            "core/shared/manual-gate",
            "core/shared/vyos-image-artifact",
            "core/shared/vyos-image-build",
            "org/aws/object-repo",
            "org/aws/pgbackrest-repo",
            "org/azure/object-repo",
            "org/azure/pgbackrest-repo",
            "org/gcp/cloudsql-external-replica",
            "org/gcp/cloudsql-postgresql",
            "org/gcp/gsm-eso-sa",
            "org/gcp/object-repo",
            "org/gcp/pgbackrest-repo",
            "org/gcp/project-factory",
            "org/gcp/wan-cloud-nat",
            "org/gcp/wan-cloud-router",
            "org/gcp/wan-hub-network",
            "org/gcp/wan-vpn-to-edge",
            "org/hetzner/shared-control-host",
            "org/hetzner/shared-private-network",
            "org/hetzner/vyos-edge-foundation",
            "org/hetzner/wan-edge-foundation",
            "platform/azure/container-registry",
            "platform/gcp/gke-cluster",
            "platform/gcp/gke-kubeconfig",
            "platform/gcp/lab-network",
            "platform/gcp/platform-vm",
            "platform/gcp/vm-firewall-rules",
            "platform/k8s/argocd-bootstrap",
            "platform/k8s/gcp-secret-store",
            "platform/k8s/gsm-bootstrap",
            "platform/k8s/kube-dns-stub-domain",
            "platform/k8s/longhorn-dr-volume",
            "platform/k8s/runtime-bundle-secret",
            "platform/linux/containerlab",
            "platform/linux/containerlab-gui",
            "platform/linux/containerlab-healthcheck",
            "platform/linux/containerlab-lab",
            "platform/linux/containerlab-recovery",
            "platform/linux/desktop-xrdp",
            "platform/linux/eve-ng",
            "platform/linux/eve-ng-healthcheck",
            "platform/linux/eve-ng-images",
            "platform/linux/eve-ng-lab-archive",
            "platform/linux/eve-ng-labs",
            "platform/linux/gns3-healthcheck",
            "platform/linux/gns3-images",
            "platform/linux/gns3-lab-archive",
            "platform/linux/gns3-server",
            "platform/linux/gns3-starter-lab",
            "platform/linux/ops-runner",
            "platform/linux/pinned-workload",
            "platform/network/cloudflare-traffic-steering",
            "platform/network/decision-consumer",
            "platform/network/decision-dispatcher",
            "platform/network/decision-executor",
            "platform/network/decision-service",
            "platform/network/dns-routing",
            "platform/network/edge-observability",
            "platform/network/powerdns-authority",
            "platform/network/vyos-edge-wan",
            "platform/network/vyos-site-extension-edge",
            "platform/network/vyos-site-extension-onprem",
            "platform/onprem/argocd-bootstrap",
            "platform/onprem/eve-ng",
            "platform/onprem/netbox",
            "platform/onprem/netbox-db-migrate",
            "platform/onprem/platform-vm",
            "platform/onprem/postgresql-core",
            "platform/onprem/postgresql-dr-source",
            "platform/onprem/postgresql-ha",
            "platform/onprem/postgresql-ha-backup",
            "platform/onprem/rke2-cluster",
            "platform/onprem/rke2-etcd-member",
            "platform/onprem/vyos-edge",
            "platform/postgresql-ha",
            "platform/postgresql-ha-backup",
        ]

        unregistered = [m for m in production_modules if m not in _REGISTRY]
        self.assertEqual(
            [], unregistered,
            f"Production modules without validators: {unregistered}",
        )

    def test_unknown_keys_are_rejected(self) -> None:
        """Validators must reject unknown input keys."""
        with self.assertRaises(ModuleValidationError) as cm:
            validate_module_inputs(
                "core/local/quickstart",
                {"operation_id": "test", "unknown_key": "value"},
            )
        self.assertIn("unknown", str(cm.exception).lower())

    def test_lifecycle_keys_are_allowed(self) -> None:
        """Internal lifecycle keys must be allowed by all validators."""
        # These are internal keys added by the runtime, validators must allow them
        lifecycle_keys = {
            "_hyops_lifecycle_command",
            "_hyops_invocation_command",
        }
        for key in lifecycle_keys:
            try:
                validate_module_inputs(
                    "core/local/quickstart",
                    {
                        "operation_id": "test-op",
                        "declared_outcome": "Test outcome",
                        key: "apply",
                    },
                )
            except ModuleValidationError as e:
                self.fail(f"Lifecycle key {key!r} should be allowed: {e}")

    def test_new_validators_reject_unknown_keys(self) -> None:
        """New validators for previously unvalidated modules must reject unknown keys."""
        test_cases = [
            ("platform/gcp/vm-firewall-rules", {}, {"bad_key": "value"}),
            ("platform/linux/containerlab", {}, {"bad_key": "value"}),
            ("platform/linux/gns3-server", {}, {"unknown": True}),
            ("platform/linux/containerlab-healthcheck", {}, {"invalid_input": "test"}),
        ]

        for module_ref, valid_inputs, invalid_extra in test_cases:
            # Valid/empty inputs should be accepted
            try:
                validate_module_inputs(module_ref, valid_inputs)
            except ModuleValidationError as e:
                self.fail(f"Valid inputs for {module_ref} should be accepted: {e}")

            # Unknown keys should be rejected
            invalid_inputs = {**valid_inputs, **invalid_extra}
            with self.assertRaises(ModuleValidationError) as cm:
                validate_module_inputs(module_ref, invalid_inputs)
            self.assertIn("unknown", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
