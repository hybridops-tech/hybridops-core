from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from hyops.runtime.cost import CostEstimate, format_money
from hyops.runtime.gcp_cost import estimate_gcp_vm_cost, gcp_vm_lifecycle_started_at


def _sku(
    description: str,
    resource_group: str,
    units: str,
    nanos: int,
    usage_unit: str,
) -> dict:
    return {
        "description": description,
        "serviceRegions": ["europe-west2"],
        "category": {
            "usageType": "OnDemand",
            "resourceGroup": resource_group,
        },
        "pricingInfo": [
            {
                "pricingExpression": {
                    "usageUnit": usage_unit,
                    "tieredRates": [
                        {
                            "unitPrice": {
                                "units": units,
                                "nanos": nanos,
                            }
                        }
                    ],
                }
            }
        ],
    }


class GcpCostTests(unittest.TestCase):
    def test_reads_stable_vm_generation_start_from_gcp(self) -> None:
        created_at = datetime.now(timezone.utc) - timedelta(hours=2, minutes=15)
        state = {
            "outputs": {
                "vms": {
                    "eve-ng-01": {
                        "vm_id": (
                            "projects/student-project/zones/europe-west2-b/"
                            "instances/eve-ng-01"
                        )
                    }
                }
            }
        }
        with patch(
            "hyops.runtime.gcp_cost._capture",
            return_value=(0, created_at.isoformat(), ""),
        ) as capture:
            started_at = gcp_vm_lifecycle_started_at(state)

        self.assertEqual(started_at, created_at)
        capture.assert_called_once_with(
            [
                "gcloud",
                "compute",
                "instances",
                "describe",
                "eve-ng-01",
                "--project",
                "student-project",
                "--zone",
                "europe-west2-b",
                "--format=value(creationTimestamp)",
            ]
        )

    def test_uses_earliest_embedded_vm_generation_start(self) -> None:
        state = {
            "outputs": {
                "vms": {
                    "first": {
                        "vm_id": "projects/p/zones/z/instances/first",
                        "creation_timestamp": "2026-08-26T10:00:00Z",
                    },
                    "second": {
                        "vm_id": "projects/p/zones/z/instances/second",
                        "creation_timestamp": "2026-08-26T10:05:00Z",
                    },
                }
            }
        }

        started_at = gcp_vm_lifecycle_started_at(state)

        self.assertEqual(
            started_at,
            datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
        )

    def test_formats_estimated_amount(self) -> None:
        estimate = CostEstimate(True, hourly=Decimal("0.5"), currency="USD")
        self.assertEqual(estimate.amount_for_seconds(5400), Decimal("0.75"))
        self.assertEqual(format_money(estimate.hourly, estimate.currency), "USD 0.50")

    def test_estimates_compute_and_disk_from_deployed_inputs(self) -> None:
        skus = [
            _sku("N2 Instance Core running in London", "CPU", "0", 50_000_000, "h"),
            _sku("N2 Instance Ram running in London", "RAM", "0", 10_000_000, "GiBy.h"),
            _sku("Storage PD Capacity in London", "PDStandard", "0", 40_000_000, "GiBy.mo"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "inputs.yml"
            inputs.write_text(
                "machine_type: n2-standard-8\n"
                "boot_disk_type: pd-standard\n"
                "boot_disk_size_gb: 100\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "hyops.runtime.gcp_cost._machine_shape",
                    return_value=(8, Decimal("32"), ""),
                ),
                patch("hyops.runtime.gcp_cost._access_token", return_value=("token", "")),
                patch(
                    "hyops.runtime.gcp_cost._public_compute_skus",
                    return_value=(skus, ""),
                ),
            ):
                estimate = estimate_gcp_vm_cost(
                    project_id="student-project",
                    zone="europe-west2-b",
                    state={"rerun_inputs_file": str(inputs)},
                )

        self.assertTrue(estimate.available)
        self.assertEqual(estimate.hourly, Decimal("0.7255"))
        self.assertIn("network charges excluded", estimate.basis)

    def test_returns_unavailable_when_pricing_inputs_are_absent(self) -> None:
        estimate = estimate_gcp_vm_cost(
            project_id="student-project",
            zone="europe-west2-b",
            state={},
        )
        self.assertFalse(estimate.available)
        self.assertIn("inputs", estimate.detail)

    def test_multiplies_shared_shape_by_deployed_vm_count(self) -> None:
        skus = [
            _sku("N2 Instance Core running in London", "CPU", "0", 50_000_000, "h"),
            _sku("N2 Instance Ram running in London", "RAM", "0", 10_000_000, "GiBy.h"),
            _sku("Storage PD Capacity in London", "PDStandard", "0", 40_000_000, "GiBy.mo"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "inputs.yml"
            inputs.write_text(
                "machine_type: n2-standard-8\n"
                "boot_disk_type: pd-standard\n"
                "boot_disk_size_gb: 100\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "hyops.runtime.gcp_cost._machine_shape",
                    return_value=(8, Decimal("32"), ""),
                ),
                patch("hyops.runtime.gcp_cost._access_token", return_value=("token", "")),
                patch(
                    "hyops.runtime.gcp_cost._public_compute_skus",
                    return_value=(skus, ""),
                ),
            ):
                estimate = estimate_gcp_vm_cost(
                    project_id="student-project",
                    zone="europe-west2-b",
                    state={
                        "rerun_inputs_file": str(inputs),
                        "outputs": {"vms": {"vm-1": {}, "vm-2": {}}},
                    },
                )

        self.assertTrue(estimate.available)
        self.assertEqual(estimate.hourly, Decimal("1.4510"))
        self.assertIn("2 VMs", estimate.basis)


if __name__ == "__main__":
    unittest.main()
