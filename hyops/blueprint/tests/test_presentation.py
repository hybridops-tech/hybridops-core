"""Tests for concise blueprint step presentation."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from hyops.blueprint.command import (
    _destroy_preview_label,
    _step_display_label,
    _step_presentation,
)
from hyops.runtime.module_state import write_module_state


class BlueprintPresentationTest(TestCase):
    def test_destroy_preview_uses_readable_label(self):
        step = {
            "id": "gcp_eve_ng_healthcheck",
            "presentation": {"label": "EVE-NG health checks"},
        }

        self.assertEqual(_step_display_label(step), "EVE-NG health checks")
        self.assertEqual(
            _destroy_preview_label(step, "ok"),
            "EVE-NG health checks",
        )

    def test_undeclared_step_label_is_humanised(self):
        self.assertEqual(
            _step_display_label({"id": "gcp_wan_vpn_to_edge"}),
            "GCP WAN VPN To Edge",
        )
        self.assertEqual(
            _step_display_label({"id": "postgres_ha_vms"}),
            "PostgreSQL HA VMs",
        )
        self.assertEqual(
            _step_display_label({"id": "gns3_healthcheck"}),
            "GNS3 health checks",
        )
        self.assertEqual(
            _step_display_label({"id": "template_image_ubuntu_22_04"}),
            "Template Image Ubuntu 22.04",
        )

    def test_destroy_preview_marks_retained_or_absent_resources(self):
        retained = {
            "id": "template",
            "presentation": {"label": "Ubuntu template"},
            "retain_on_destroy": True,
        }
        absent = {
            "id": "network",
            "presentation": {"label": "Private network"},
        }

        self.assertEqual(
            _destroy_preview_label(retained, "ok"),
            "Ubuntu template (retained)",
        )
        self.assertEqual(
            _destroy_preview_label(absent, "destroyed"),
            "Private network (already absent)",
        )

    def test_uses_published_image_count_and_declared_items(self):
        step = {
            "id": "images",
            "module_ref": "platform/linux/eve-ng-images",
            "state_instance": "images",
            "presentation": {
                "label": "Lab images",
                "success": "ready",
                "items_label": "images",
                "items": ["Alpine Linux", "NETem"],
            },
        }

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_module_state(
                state_dir,
                step["module_ref"],
                {
                    "status": "ok",
                    "outputs": {"eveng_images_requested_count": 2},
                },
                state_instance=step["state_instance"],
            )

            label, detail, item_line = _step_presentation(
                step,
                state_dir=state_dir,
                progress_after=80,
            )

        self.assertEqual(label, "Lab images")
        self.assertEqual(detail, "ready, 2 images, overall 80%")
        self.assertEqual(item_line, "  images: Alpine Linux, NETem")

    def test_uses_published_health_status(self):
        step = {
            "id": "health",
            "module_ref": "platform/linux/eve-ng-healthcheck",
            "state_instance": "health",
            "presentation": {"label": "EVE-NG health checks"},
        }

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_module_state(
                state_dir,
                step["module_ref"],
                {
                    "status": "ok",
                    "outputs": {"eveng_health_status": "healthy"},
                },
                state_instance=step["state_instance"],
            )

            label, detail, item_line = _step_presentation(
                step,
                state_dir=state_dir,
                progress_after=100,
            )

        self.assertEqual(label, "EVE-NG health checks")
        self.assertEqual(detail, "healthy, overall 100%")
        self.assertEqual(item_line, "")
