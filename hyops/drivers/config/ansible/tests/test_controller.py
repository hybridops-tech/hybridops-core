import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from hyops.drivers.config.ansible.controller import check_controller


class ControllerReadinessTest(TestCase):
    def test_runtime_collection_path_is_checked(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            runtime_root = Path(raw_tmp)
            collection_root = (
                runtime_root / "state" / "ansible" / "galaxy_collections"
            )
            collection_root.mkdir(parents=True)

            with patch(
                "hyops.drivers.config.ansible.controller.ensure_hybridops_collections_available",
                return_value="",
            ) as ensure:
                error = check_controller(
                    {"env": {}, "runtime_root": runtime_root}
                )

        self.assertEqual(error, "")
        checked_env = ensure.call_args.args[0]
        self.assertIn(
            str(collection_root),
            checked_env["ANSIBLE_COLLECTIONS_PATH"].split(os.pathsep),
        )

    def test_explicit_collection_path_is_preserved(self):
        with patch(
            "hyops.drivers.config.ansible.controller.ensure_hybridops_collections_available",
            return_value="missing collections",
        ) as ensure:
            error = check_controller(
                {
                    "env": {"ANSIBLE_COLLECTIONS_PATH": "/opt/hybridops/collections"},
                    "runtime_root": "/tmp/runtime",
                }
            )

        self.assertEqual(error, "missing collections")
        self.assertEqual(
            ensure.call_args.args[0]["ANSIBLE_COLLECTIONS_PATH"],
            "/opt/hybridops/collections",
        )
