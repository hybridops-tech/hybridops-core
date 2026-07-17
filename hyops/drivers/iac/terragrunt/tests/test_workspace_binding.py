"""Backend binding recovery after an interrupted local state-summary write."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hyops.drivers.iac.terragrunt._internal.workspace_binding import (
    check_backend_binding_drift,
)
from hyops.runtime.module_state import module_state_path


class LocalBackendBindingRecoveryTests(unittest.TestCase):
    def test_valid_terraform_state_allows_summary_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            summary = module_state_path(
                state_root,
                "platform/gcp/lab-network",
                state_instance="gcp_eve_ng_network",
            )
            summary.parent.mkdir(parents=True)
            summary.write_text("", encoding="utf-8")
            terraform_state = (
                state_root
                / "terraform"
                / "platform__gcp__lab-network__gcp_eve_ng_network.tfstate"
            )
            terraform_state.parent.mkdir(parents=True)
            terraform_state.write_text(
                json.dumps({"version": 4, "serial": 1, "resources": []}),
                encoding="utf-8",
            )

            error, warning = check_backend_binding_drift(
                state_root=state_root,
                module_ref="platform/gcp/lab-network",
                state_instance="gcp_eve_ng_network",
                current_binding={"mode": "local"},
                allow_drift=False,
            )

        self.assertEqual(error, "")
        self.assertIn("next successful apply will rebuild", warning)

    def test_corrupt_terraform_state_keeps_guard_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            summary = module_state_path(
                state_root,
                "platform/gcp/lab-network",
                state_instance="gcp_eve_ng_network",
            )
            summary.parent.mkdir(parents=True)
            summary.write_text("", encoding="utf-8")
            terraform_state = (
                state_root
                / "terraform"
                / "platform__gcp__lab-network__gcp_eve_ng_network.tfstate"
            )
            terraform_state.parent.mkdir(parents=True)
            terraform_state.write_text("", encoding="utf-8")

            error, warning = check_backend_binding_drift(
                state_root=state_root,
                module_ref="platform/gcp/lab-network",
                state_instance="gcp_eve_ng_network",
                current_binding={"mode": "local"},
                allow_drift=False,
            )

        self.assertIn("failed to read module state", error)
        self.assertEqual(warning, "")


if __name__ == "__main__":
    unittest.main()
