from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.drivers.config.ansible import runtime_env
from hyops.drivers.config.ansible.runtime_env import prepare_ansible_controller_env


class PrepareAnsibleControllerEnvTests(unittest.TestCase):
    def test_vendor_package_keeps_existing_copy_when_staging_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            source = tmp / "source"
            destination = tmp / "vendor" / "jmespath"
            source.mkdir()
            destination.mkdir(parents=True)
            (destination / "__init__.py").write_text("existing", encoding="utf-8")

            with patch(
                "hyops.drivers.config.ansible.runtime_env.tempfile.mkdtemp",
                side_effect=PermissionError("read only"),
            ):
                installed = runtime_env._vendor_controller_package(
                    [source], destination
                )

            self.assertTrue(installed)
            self.assertEqual(
                (destination / "__init__.py").read_text(encoding="utf-8"),
                "existing",
            )

    def test_vendor_package_recovers_from_partial_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            broken = tmp / "broken"
            healthy = tmp / "healthy"
            destination = tmp / "vendor" / "jmespath"
            for source in (broken, healthy):
                source.mkdir()
            (broken / "__init__.py").write_text("broken", encoding="utf-8")
            (healthy / "__init__.py").write_text("healthy", encoding="utf-8")
            (healthy / "parser.py").write_text("parser", encoding="utf-8")

            copytree = runtime_env.shutil.copytree

            def fail_mid_copy(source: Path, target: Path, *args, **kwargs):
                if Path(source) == broken:
                    target.mkdir(parents=True)
                    (target / "__init__.py").write_text("partial", encoding="utf-8")
                    raise OSError("copy failed")
                return copytree(source, target, *args, **kwargs)

            with patch(
                "hyops.drivers.config.ansible.runtime_env.shutil.copytree",
                side_effect=fail_mid_copy,
            ):
                installed = runtime_env._vendor_controller_package(
                    [broken, healthy], destination
                )

            self.assertTrue(installed)
            self.assertEqual(
                (destination / "__init__.py").read_text(encoding="utf-8"),
                "healthy",
            )
            self.assertTrue((destination / "parser.py").is_file())
            self.assertEqual(list(destination.parent.glob(".jmespath.*")), [])

            (healthy / "parser.py").write_text("updated", encoding="utf-8")
            self.assertTrue(
                runtime_env._vendor_controller_package([healthy], destination)
            )
            self.assertEqual(
                (destination / "parser.py").read_text(encoding="utf-8"),
                "updated",
            )

    def test_vendors_core_managed_controller_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            runtime_root = tmp / "runtime"
            ansible_bin = tmp / "ansible-playbook"
            ansible_bin.write_text(f"#!{sys.executable}\n", encoding="utf-8")

            package_roots: dict[str, Path] = {}
            for package_name in ("jmespath", "netaddr"):
                package_root = tmp / "packages" / package_name
                package_root.mkdir(parents=True)
                (package_root / "__init__.py").write_text("", encoding="utf-8")
                package_roots[package_name] = package_root

            def find_spec(package_name: str):
                package_root = package_roots[package_name]
                return SimpleNamespace(submodule_search_locations=[str(package_root)])

            completed = subprocess.CompletedProcess(
                args=[sys.executable], returncode=0, stdout="", stderr=""
            )
            env: dict[str, str] = {}
            with (
                patch(
                    "hyops.drivers.config.ansible.runtime_env.importlib.util.find_spec",
                    side_effect=find_spec,
                ),
                patch(
                    "hyops.drivers.config.ansible.runtime_env.subprocess.run",
                    return_value=completed,
                ) as run,
            ):
                error = prepare_ansible_controller_env(
                    env=env,
                    runtime_root=runtime_root,
                    ansible_bin=str(ansible_bin),
                )

            self.assertEqual(error, "")
            vendor_dir = runtime_root / "state" / "python" / "vendor"
            self.assertTrue((vendor_dir / "jmespath" / "__init__.py").is_file())
            self.assertTrue((vendor_dir / "netaddr" / "__init__.py").is_file())
            self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], str(vendor_dir))
            self.assertEqual(run.call_args.args[0][0], sys.executable)


if __name__ == "__main__":
    unittest.main()
