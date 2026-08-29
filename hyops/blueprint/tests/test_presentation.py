"""Tests for concise blueprint step presentation."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import (
    _collect_deploy_risk_signals,
    _confirm_deploy_if_needed,
    _destroy_preview_label,
    _gcp_cost_estimate_with_progress,
    _new_step_failure_detail,
    _prompt_yes_no,
    _step_failure_state,
    _step_display_label,
    _step_presentation,
)
from hyops.runtime.cost import CostEstimate
from hyops.runtime.module_state import write_module_state


class BlueprintPresentationTest(TestCase):
    def test_yes_no_prompt_retries_invalid_input(self):
        output = io.StringIO()

        with (
            patch("builtins.input", side_effect=["1", "y"]) as prompt,
            patch("sys.stdout", output),
        ):
            confirmed = _prompt_yes_no("Proceed? [y/N]: ")

        self.assertTrue(confirmed)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(output.getvalue(), "invalid response; enter y or n\n")

    def test_yes_no_prompt_keeps_no_as_default(self):
        with patch("builtins.input", return_value=""):
            self.assertFalse(_prompt_yes_no("Proceed? [y/N]: "))

    def test_yes_no_prompt_accepts_bracketed_terminal_input(self):
        with patch("builtins.input", return_value="\x1b[200~y\x1b[201~"):
            self.assertTrue(_prompt_yes_no("Proceed? [y/N]: "))

    def test_surfaces_new_module_failure_from_state(self):
        step = {
            "id": "images",
            "module_ref": "platform/linux/eve-ng-images",
            "state_instance": "images",
        }

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            paths = type("Paths", (), {"state_dir": state_dir})()
            previous = _step_failure_state(step, paths)
            write_module_state(
                state_dir,
                step["module_ref"],
                {
                    "run_id": "apply-test",
                    "status": "error",
                    "last_error": (
                        "ansible apply failed: IOL licence does not match this "
                        "EVE-NG host. Hostname: eve-ng-01. Host ID: 500a0232."
                    ),
                },
                state_instance=step["state_instance"],
            )

            detail = _new_step_failure_detail(step, paths, previous)

        self.assertEqual(
            detail,
            "configuration apply failed: IOL licence does not match this EVE-NG "
            "host. Hostname: eve-ng-01. Host ID: 500a0232.",
        )

    def test_does_not_surface_stale_module_failure(self):
        step = {
            "id": "images",
            "module_ref": "platform/linux/eve-ng-images",
            "state_instance": "images",
        }

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            paths = type("Paths", (), {"state_dir": state_dir})()
            write_module_state(
                state_dir,
                step["module_ref"],
                {
                    "run_id": "apply-old",
                    "status": "error",
                    "last_error": "old failure",
                },
                state_instance=step["state_instance"],
            )
            previous = _step_failure_state(step, paths)

            detail = _new_step_failure_detail(step, paths, previous)

        self.assertEqual(detail, "")

    def test_destroyed_steps_do_not_trigger_deploy_risk_warning(self):
        step = {
            "id": "network",
            "module_ref": "platform/gcp/lab-network",
            "state_instance": "network",
            "action": "deploy",
        }
        payload = {"steps": [step]}
        paths = type("Paths", (), {"state_dir": Path("/tmp/state")})()

        with patch(
            "hyops.blueprint.command.module_state_status",
            return_value="destroyed",
        ):
            self.assertEqual(_collect_deploy_risk_signals(payload, paths), [])

    def test_active_deploy_warning_is_concise_by_default(self):
        step = {
            "id": "gcp_eve_ng_network",
            "module_ref": "platform/gcp/lab-network",
            "state_instance": "gcp_eve_ng_network",
            "action": "deploy",
            "presentation": {"label": "Private lab network"},
        }
        payload = {"steps": [step]}
        paths = type(
            "Paths",
            (),
            {"state_dir": Path("/tmp/state"), "root": Path("/tmp/demo-lab")},
        )()
        ns = type("Namespace", (), {"yes": False, "json": False, "env": "demo-lab"})()
        output = io.StringIO()

        with (
            patch(
                "hyops.blueprint.command.module_state_status",
                return_value="ok",
            ),
            patch("hyops.blueprint.command.sys.stdin", io.StringIO()),
            patch("hyops.blueprint.command.sys.stdout", output),
        ):
            self.assertEqual(_confirm_deploy_if_needed(ns, payload, paths), 0)

        rendered = output.getvalue()
        self.assertIn(
            "WARN: deploy may change 1 active blueprint step in env=demo-lab.",
            rendered,
        )
        self.assertIn("  - Private lab network (state=ok)", rendered)
        self.assertNotIn("platform/gcp/lab-network", rendered)
        self.assertNotIn("gcp_eve_ng_network", rendered)

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
                    "outputs": {
                        "eveng_images_requested_count": 3,
                        "eveng_images_installed_count": 2,
                    },
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

    def test_lists_configured_qemu_and_iol_images(self):
        step = {
            "id": "images",
            "module_ref": "platform/linux/eve-ng-images",
            "state_instance": "images",
            "presentation": {
                "label": "Lab images",
                "success": "ready",
                "items_label": "images",
                "items": ["stale static item"],
            },
            "inputs": {
                "eveng_images_list": [
                    {
                        "name": "linux-alpine-3.21.3.tar.gz",
                        "type": "qemu",
                        "url": "https://example.invalid/alpine",
                    },
                    {
                        "label": "Cisco IOL L2 15.2d",
                        "name": "iol-i86bi-linux-l2-adventerprisek9-15.2d-clean.tar.gz",
                        "type": "iol",
                        "url": "https://example.invalid/iol-l2",
                    },
                    {
                        "label": "Operator firewall image",
                        "name": "vendor-firewall.tar.gz",
                        "type": "qemu",
                        "url": "https://example.invalid/firewall",
                    },
                ]
            },
        }

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_module_state(
                state_dir,
                step["module_ref"],
                {
                    "status": "ok",
                    "outputs": {"eveng_images_requested_count": 3},
                },
                state_instance=step["state_instance"],
            )

            label, detail, item_line = _step_presentation(
                step,
                state_dir=state_dir,
                progress_after=80,
            )

        self.assertEqual(label, "Lab images")
        self.assertEqual(detail, "ready, 3 images, overall 80%")
        self.assertEqual(
            item_line,
            "  images: Alpine Linux, Cisco IOL L2 15.2d, Operator firewall image",
        )

    def test_lists_large_image_sets_one_per_line(self):
        image_names = [
            "Alpine Linux",
            "NETem",
            "Tiny Core Linux",
            "Ubuntu Server",
            "Cisco IOL L2 15.2d",
        ]
        step = {
            "id": "images",
            "module_ref": "platform/linux/eve-ng-images",
            "state_instance": "images",
            "presentation": {
                "label": "Lab images",
                "items_label": "images",
                "items": image_names,
            },
        }

        with TemporaryDirectory() as tmp:
            _, _, item_line = _step_presentation(
                step,
                state_dir=Path(tmp),
                progress_after=80,
            )

        self.assertEqual(
            item_line,
            "  images:\n"
            "    - Alpine Linux\n"
            "    - NETem\n"
            "    - Tiny Core Linux\n"
            "    - Ubuntu Server\n"
            "    - Cisco IOL L2 15.2d",
        )

    def test_lists_every_published_local_image_instead_of_url_defaults(self):
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
            "inputs": {
                "eveng_images_source": "local",
                "eveng_images_list": [
                    {
                        "name": "linux-alpine-3.21.3.tar.gz",
                        "label": "Alpine Linux",
                    },
                    {
                        "name": "linux-netem.tar.gz",
                        "label": "NETem",
                    },
                ],
            },
        }

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_module_state(
                state_dir,
                step["module_ref"],
                {
                    "status": "ok",
                    "outputs": {
                        "eveng_images_installed_count": 6,
                        "eveng_images_installed_names": [
                            "linux-alpine-3.21.3.tar.gz",
                            "linux-netem.tar.gz",
                            "linux-ubuntu-24.04-server.tar.gz",
                            "iol-i86bi-linux-l2-adventerprisek9-15.2d.tar.gz",
                            "veos-lab-4.34.2F.tar.gz",
                            "vios-adventerprisek9-m.SPA.159-3.M6.tar.gz",
                        ],
                    },
                },
                state_instance=step["state_instance"],
            )

            _, detail, item_line = _step_presentation(
                step,
                state_dir=state_dir,
                progress_after=80,
            )

        self.assertEqual(detail, "ready, 6 images, overall 80%")
        self.assertEqual(
            item_line,
            "  images:\n"
            "    - Alpine Linux\n"
            "    - NETem\n"
            "    - Ubuntu Server\n"
            "    - iol-i86bi-linux-l2-adventerprisek9-15.2d\n"
            "    - veos-lab-4.34.2F\n"
            "    - vios-adventerprisek9-m.SPA.159-3.M6",
        )

    def test_cost_estimate_progress_does_not_show_elapsed_time(self):
        paths = type("Paths", (), {"meta_dir": Path("/tmp/meta")})()
        estimate = CostEstimate(True)

        with (
            patch("hyops.blueprint.command.ProgressDisplay") as progress_class,
            patch(
                "hyops.blueprint.command.estimate_gcp_vm_cost",
                return_value=estimate,
            ),
        ):
            result = _gcp_cost_estimate_with_progress(
                project_id="test-project",
                zone="europe-west2-a",
                state={},
                paths=paths,
            )

        self.assertIs(result, estimate)
        progress_class.assert_called_once_with(show_elapsed=False)
        progress_class.return_value.start.assert_called_once_with(
            "cloud-cost",
            "Estimating cloud cost",
            plain="estimating cloud cost",
        )
