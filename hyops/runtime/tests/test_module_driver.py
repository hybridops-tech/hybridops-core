import tempfile
from pathlib import Path
from unittest import TestCase, mock

from hyops.drivers import registry as driver_registry
from hyops.drivers.registry import DriverRegistry
from hyops.runtime.module_driver import check_driver_controller, inspect_module_state


def _driver(_request):
    return {"status": "ok", "run_id": "test", "normalized_outputs": {}}


class ModuleDriverCapabilityTest(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.module_root = Path(self.tempdir.name)
        module_dir = self.module_root / "platform" / "test" / "service"
        module_dir.mkdir(parents=True)
        (module_dir / "spec.yml").write_text(
            """
module_ref: platform/test/service
execution:
  driver: test/driver
  profile: test@v1
  pack_ref:
    id: test/service@v1
""".strip()
            + "\n",
            encoding="utf-8",
        )

    def test_module_state_inspection_uses_declared_driver(self):
        registry = DriverRegistry()
        registry.register(
            "test/driver",
            _driver,
            state_inspector=lambda request: ("stale", str(request["reason"])),
        )

        result = inspect_module_state(
            module_ref="platform/test/service",
            module_root=self.module_root,
            request={"reason": "state drift"},
            registry=registry,
        )

        self.assertEqual(result, ("stale", "state drift"))

    def test_driver_controller_check_uses_registered_capability(self):
        registry = DriverRegistry()
        registry.register(
            "test/driver",
            _driver,
            controller_check=lambda request: str(request["error"]),
        )

        result = check_driver_controller(
            driver_ref="test/driver",
            request={"error": "controller dependency missing"},
            registry=registry,
        )

        self.assertEqual(result, "controller dependency missing")

    def test_default_registry_is_resolved_at_call_time(self):
        registry = DriverRegistry()
        registry.register(
            "test/driver",
            _driver,
            controller_check=lambda _request: "replacement registry",
        )

        with mock.patch.object(driver_registry, "REGISTRY", registry):
            result = check_driver_controller(
                driver_ref="test/driver",
                request={},
            )

        self.assertEqual(result, "replacement registry")
