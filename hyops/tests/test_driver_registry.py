from unittest import TestCase

from hyops.drivers.registry import DriverRegistry


def _driver(_request):
    return {"status": "ok", "run_id": "test", "normalized_outputs": {}}


class DriverRegistryCapabilityTest(TestCase):
    def test_optional_capabilities_keep_default_driver_behaviour(self):
        registry = DriverRegistry()
        registry.register("test/driver", _driver)

        self.assertEqual(registry.check_controller("test/driver", {}), "")
        self.assertEqual(registry.inspect_state("test/driver", {}), ("safe", ""))

    def test_registered_capabilities_are_dispatched(self):
        registry = DriverRegistry()
        registry.register(
            "test/driver",
            _driver,
            controller_check=lambda request: str(request["controller_error"]),
            state_inspector=lambda request: ("stale", str(request["detail"])),
        )

        self.assertEqual(
            registry.check_controller(
                "test/driver", {"controller_error": "dependency unavailable"}
            ),
            "dependency unavailable",
        )
        self.assertEqual(
            registry.inspect_state("test/driver", {"detail": "remote object missing"}),
            ("stale", "remote object missing"),
        )

    def test_invalid_state_inspection_status_is_rejected(self):
        registry = DriverRegistry()
        registry.register(
            "test/driver",
            _driver,
            state_inspector=lambda _request: ("unknown", ""),
        )

        with self.assertRaisesRegex(ValueError, "invalid status"):
            registry.inspect_state("test/driver", {})

    def test_non_callable_capability_is_rejected_at_registration(self):
        registry = DriverRegistry()

        with self.assertRaisesRegex(TypeError, "state inspector is not callable"):
            registry.register("test/driver", _driver, state_inspector="invalid")
