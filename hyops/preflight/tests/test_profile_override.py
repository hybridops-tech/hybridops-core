from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from hyops.preflight.command import run_module_driver_preflight


class ModulePreflightProfileOverrideTest(TestCase):
    def test_profile_override_is_passed_to_driver(self) -> None:
        captured = {}

        def driver(request):
            captured.update(request)
            return {"status": "ok"}

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(
                root=root,
                state_dir=root / "state",
                logs_dir=root / "logs",
                meta_dir=root / "meta",
                credentials_dir=root / "credentials",
                work_dir=root / "work",
            )
            resolved = SimpleNamespace(
                execution={"driver": "test/driver", "profile": "default@v1"},
                module_dir=root / "module",
                inputs={},
                required_credentials=[],
                outputs_publish=[],
            )

            with (
                patch("hyops.preflight.command.ensure_layout"),
                patch("hyops.preflight.command.resolve_module", return_value=resolved),
                patch("hyops.preflight.command.REGISTRY.resolve", return_value=driver),
                patch("hyops.preflight.command.new_run_id", return_value="preflight-test"),
                patch(
                    "hyops.preflight.command.init_evidence_dir",
                    return_value=root / "logs" / "preflight-test",
                ),
            ):
                result = run_module_driver_preflight(
                    paths=paths,
                    env_name="test",
                    module_ref="platform/test/module",
                    module_root=root / "modules",
                    inputs_file=None,
                    profile_override="override@v2",
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(captured["execution"]["profile"], "override@v2")
