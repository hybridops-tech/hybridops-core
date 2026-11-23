from __future__ import annotations

import importlib
import os
import sys
import unittest
from importlib.metadata import PathDistribution
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hyops.authority import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityRequirement,
    AuthorityResolver,
)
from hyops.authority.plugins import ENTRY_POINT_GROUP, register_plugins
from hyops.authority.registry import AuthorityProviderRegistry


class _EntryPoints(list):
    def select(self, *, group: str):
        return [item for item in self if item.group == group]


class _EntryPoint:
    group = ENTRY_POINT_GROUP

    def __init__(self, name: str, hook, *, distribution: str = "fixture-plugin") -> None:
        self.name = name
        self._hook = hook
        self.dist = _Distribution(distribution)

    def load(self):
        return self._hook


class _Distribution:
    def __init__(self, name: str, version: str = "1.2.3") -> None:
        self.metadata = {"Name": name}
        self.version = version


def _provider(name: str):
    class PluginProvider:
        capabilities = frozenset({"change_control"})

        def validate_configuration(self, declaration, context) -> None:
            del declaration, context

        def evaluate(self, declaration, context):
            del declaration, context

    PluginProvider.name = name
    return PluginProvider()


class AuthorityPluginTests(unittest.TestCase):
    def test_plugin_hook_registers_provider(self) -> None:
        class PluginProvider:
            name = "external"
            capabilities = frozenset({"change_control"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context):
                del declaration, context

        entry_points = _EntryPoints(
            [
                _EntryPoint(
                    "external-provider",
                    lambda registry: registry.register(PluginProvider()),
                )
            ]
        )
        registry = AuthorityProviderRegistry()

        with (
            patch.dict(os.environ, {"HYOPS_NO_PLUGINS": ""}),
            patch("importlib.metadata.entry_points", return_value=entry_points),
        ):
            register_plugins(registry)

        self.assertEqual(registry.names(), ("external",))
        identity = registry.registration("external").identity
        self.assertEqual(identity.source, "plugin")
        self.assertEqual(identity.distribution, "fixture-plugin")
        self.assertEqual(identity.version, "1.2.3")

    def test_plugins_are_registered_in_entrypoint_name_order(self) -> None:
        calls = []
        entry_points = _EntryPoints(
            [
                _EntryPoint(
                    "z-provider",
                    lambda registry: (
                        calls.append("z"), registry.register(_provider("z_provider"))
                    ),
                ),
                _EntryPoint(
                    "a-provider",
                    lambda registry: (
                        calls.append("a"), registry.register(_provider("a_provider"))
                    ),
                ),
            ]
        )

        with (
            patch.dict(os.environ, {"HYOPS_NO_PLUGINS": ""}),
            patch("importlib.metadata.entry_points", return_value=entry_points),
        ):
            register_plugins(AuthorityProviderRegistry())

        self.assertEqual(calls, ["a", "z"])

    def test_plugins_can_be_disabled(self) -> None:
        with (
            patch.dict(os.environ, {"HYOPS_NO_PLUGINS": "1"}),
            patch("importlib.metadata.entry_points") as entry_points,
        ):
            register_plugins(AuthorityProviderRegistry())

        entry_points.assert_not_called()

    def test_non_callable_entrypoint_is_rejected(self) -> None:
        entry_points = _EntryPoints([_EntryPoint("invalid", object())])
        with (
            patch.dict(os.environ, {"HYOPS_NO_PLUGINS": ""}),
            patch("importlib.metadata.entry_points", return_value=entry_points),
            self.assertRaisesRegex(RuntimeError, "entrypoint is not callable"),
        ):
            register_plugins(AuthorityProviderRegistry())

    def test_registry_rejects_incomplete_plugin_provider(self) -> None:
        class IncompleteProvider:
            name = "incomplete"
            capabilities = frozenset({"resource_authority"})

        registry = AuthorityProviderRegistry()
        with self.assertRaisesRegex(TypeError, "validate_configuration"):
            registry.register(IncompleteProvider())

    def test_registry_rejects_invalid_plugin_identity(self) -> None:
        class InvalidProvider:
            name = "invalid provider"
            capabilities = frozenset({"resource authority"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context):
                del declaration, context

        with self.assertRaisesRegex(ValueError, "name has an invalid format"):
            AuthorityProviderRegistry().register(InvalidProvider())

    def test_registry_rejects_noncanonical_or_mutable_provider_metadata(self) -> None:
        provider = _provider(" External ")
        with self.assertRaisesRegex(ValueError, "canonical lowercase form"):
            AuthorityProviderRegistry().register(provider)

        provider = _provider("external")
        provider.capabilities = ["change_control"]
        with self.assertRaisesRegex(TypeError, "must be a frozenset"):
            AuthorityProviderRegistry().register(provider)

    def test_registry_uses_immutable_provider_metadata_snapshot(self) -> None:
        class MutableProvider:
            name = "external"
            capabilities = frozenset({"change_control"})

            def validate_configuration(self, declaration, context) -> None:
                del declaration, context

            def evaluate(self, declaration, context) -> AuthorityEvaluation:
                del declaration, context
                return AuthorityEvaluation(True, "ready", "admitted")

        provider = MutableProvider()
        registry = AuthorityProviderRegistry()
        registry.register(provider)

        provider.name = "changed"
        provider.capabilities = frozenset({"resource_authority"})

        registration = registry.registration("external")
        receipt = AuthorityResolver(registry).enforce(
            AuthorityRequirement("change", "change_control"),
            {
                "change": AuthorityDeclaration(
                    "change", "change_control", "external"
                )
            },
            AuthorityContext(Path("/tmp"), Path("/tmp/state"), {}),
        )

        self.assertEqual(registration.name, "external")
        self.assertEqual(registration.capabilities, frozenset({"change_control"}))
        self.assertEqual(receipt.provider, "external")

    def test_direct_external_provider_is_not_attributed_to_core(self) -> None:
        provider = _provider("external")
        type(provider).__module__ = "external_authority.provider"
        registry = AuthorityProviderRegistry()

        registry.register(provider)

        identity = registry.registration("external").identity
        self.assertEqual(identity.source, "direct")
        self.assertEqual(identity.distribution, "unknown")
        self.assertEqual(identity.version, "unknown")
        self.assertTrue(
            identity.entry_point.startswith("external_authority.provider:")
        )

    def test_registry_rejects_partial_interval_provider_contract(self) -> None:
        provider = _provider("partial")
        provider.interval_verifiable = lambda *args: True

        with self.assertRaisesRegex(TypeError, "both interval_verifiable"):
            AuthorityProviderRegistry().register(provider)

    def test_plugin_registration_is_atomic(self) -> None:
        def fail(_registry) -> None:
            raise RuntimeError("registration failed")

        entry_points = _EntryPoints(
            [
                _EntryPoint(
                    "a-provider",
                    lambda registry: registry.register(_provider("external")),
                ),
                _EntryPoint("b-provider", fail),
            ]
        )
        registry = AuthorityProviderRegistry()

        with (
            patch.dict(os.environ, {"HYOPS_NO_PLUGINS": ""}),
            patch("importlib.metadata.entry_points", return_value=entry_points),
            self.assertRaisesRegex(RuntimeError, "registration failed"),
        ):
            register_plugins(registry)

        self.assertEqual(registry.names(), ())
        with self.assertRaisesRegex(RuntimeError, "discovery is incomplete"):
            registry.require_discovery_complete()

    def test_installed_entrypoint_identity_reaches_runtime_receipt(self) -> None:
        module_name = "fixture_authority_plugin"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / f"{module_name}.py").write_text(
                """\
from hyops.authority import AuthorityEvaluation

class Provider:
    name = "packaged"
    capabilities = frozenset({"change_control"})

    def validate_configuration(self, declaration, context):
        pass

    def evaluate(self, declaration, context):
        return AuthorityEvaluation(True, "ready", "admitted")

def register(registry):
    registry.register(Provider())
""",
                encoding="utf-8",
            )
            dist_info = root / "fixture_authority-4.5.6.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: fixture-authority\nVersion: 4.5.6\n",
                encoding="utf-8",
            )
            (dist_info / "entry_points.txt").write_text(
                f"[{ENTRY_POINT_GROUP}]\npackaged = {module_name}:register\n",
                encoding="utf-8",
            )
            distribution = PathDistribution(dist_info)
            entry_points = _EntryPoints(distribution.entry_points)
            registry = AuthorityProviderRegistry()
            sys.path.insert(0, str(root))
            importlib.invalidate_caches()
            try:
                with (
                    patch.dict(os.environ, {"HYOPS_NO_PLUGINS": ""}),
                    patch(
                        "importlib.metadata.entry_points",
                        return_value=entry_points,
                    ),
                ):
                    register_plugins(registry)
                receipt = AuthorityResolver(registry).enforce(
                    AuthorityRequirement("change", "change_control"),
                    {
                        "change": AuthorityDeclaration(
                            "change", "change_control", "packaged"
                        )
                    },
                    AuthorityContext(root, root, {}),
                )
            finally:
                sys.path.remove(str(root))
                sys.modules.pop(module_name, None)

        self.assertEqual(receipt.provider_identity.source, "plugin")
        self.assertEqual(receipt.provider_identity.distribution, "fixture-authority")
        self.assertEqual(receipt.provider_identity.version, "4.5.6")
        self.assertEqual(
            receipt.to_evidence()["provider_identity"]["contract_version"],
            "1",
        )


if __name__ == "__main__":
    unittest.main()
