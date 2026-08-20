from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import run_rebuild


class BlueprintRebuildArchiveModeTest(TestCase):
    def test_rebuild_without_generic_archive_does_not_set_skip_archive(self) -> None:
        payload = {
            "blueprint_ref": "gcp/containerlab@v1",
            "mode": "hybrid",
            "order": [],
            "steps": [],
            "archive_before_destroy": {},
        }
        ns = SimpleNamespace(
            execute=True,
            json=False,
            yes=True,
            root=None,
            env="containerlab-test",
            ref="gcp/containerlab@v1",
            file="",
            blueprints_root="blueprints",
            module_root="modules",
            out_dir=None,
            deps_inputs_dir=None,
            deps_force=False,
            skip_preflight=False,
        )

        runtime_paths = SimpleNamespace(
            root=Path("/tmp/hyops-containerlab-test"),
            logs_dir=Path("/tmp/hyops-containerlab-test/logs"),
        )

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=runtime_paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.new_run_id", return_value="rebuild-test"),
            patch("hyops.blueprint.command.run_destroy", return_value=0) as destroy,
            patch("hyops.blueprint.command.run_deploy", return_value=0),
        ):
            rc = run_rebuild(ns)

        self.assertEqual(rc, 0)
        destroy_ns = destroy.call_args.args[0]
        self.assertFalse(destroy_ns.skip_archive)

    def test_rebuild_with_generic_archive_keeps_skip_archive(self) -> None:
        payload = {
            "blueprint_ref": "gcp/gns3@v1",
            "mode": "hybrid",
            "order": [],
            "steps": [],
            "archive_before_destroy": {
                "module_ref": "platform/linux/gns3-lab-archive",
                "state_instance": "gns3_archive",
            },
        }
        ns = SimpleNamespace(
            execute=True,
            json=False,
            yes=True,
            root=None,
            env="gns3-test",
            ref="gcp/gns3@v1",
            file="",
            blueprints_root="blueprints",
            module_root="modules",
            out_dir=None,
            deps_inputs_dir=None,
            deps_force=False,
            skip_preflight=False,
        )

        runtime_paths = SimpleNamespace(
            root=Path("/tmp/hyops-gns3-test"),
            logs_dir=Path("/tmp/hyops-gns3-test/logs"),
        )

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=runtime_paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.new_run_id", return_value="rebuild-test"),
            patch("hyops.blueprint.command.run_destroy", return_value=0) as destroy,
            patch("hyops.blueprint.command.run_deploy", return_value=0),
        ):
            rc = run_rebuild(ns)

        self.assertEqual(rc, 0)
        destroy_ns = destroy.call_args.args[0]
        self.assertTrue(destroy_ns.skip_archive)
