from pathlib import Path
from unittest import TestCase

import yaml

from hyops.validators.platform.onprem.rke2_cluster import validate


class RKE2ClusterModuleContractTest(TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        path = (
            self.root
            / "packs"
            / "config"
            / "ansible"
            / "onprem"
            / "common"
            / "platform"
            / "50-rke2-cluster@v1.0"
            / "stack"
            / "playbook.yml"
        )
        self.plays = yaml.safe_load(path.read_text(encoding="utf-8"))

    def play(self, name: str) -> dict:
        return next(play for play in self.plays if play.get("name") == name)

    @staticmethod
    def valid_inputs() -> dict:
        return {
            "inventory_groups": {
                "rke2_servers": [{"name": "rke2-cp-01", "host": "192.0.2.10"}],
            },
            "target_user": "opsadmin",
            "target_port": 22,
            "required_env": ["RKE2_TOKEN"],
            "rke2_token_env": "RKE2_TOKEN",
            "rke2_install_version": "v1.34.12+rke2r1",
        }

    def test_exported_kubeconfig_prefers_cluster_node_address(self) -> None:
        publish = self.play("Platform/onprem/rke2-cluster (publish outputs)")
        write = next(task for task in publish["tasks"] if task.get("name") == "Write kubeconfig locally")

        api_host = write["vars"]["_api_host"]
        self.assertLess(api_host.index(".advertise_address"), api_host.index(".node_ip"))
        self.assertLess(api_host.index(".node_ip"), api_host.index(".ansible_host"))
        self.assertIn("default(_primary, true)", api_host)

        content = write["ansible.builtin.copy"]["content"]
        self.assertIn("_api_host", content)
        self.assertNotIn("_primary_ip", content)

    def test_agent_reconciliation_is_serial_and_ready_gated(self) -> None:
        agent = self.play("Platform/onprem/rke2-cluster (agent play)")
        self.assertEqual(agent["serial"], 1)

        build_vars = next(task for task in agent["pre_tasks"] if task.get("name") == "Build role vars")
        role_vars = build_vars["ansible.builtin.set_fact"]["_hyops_rke2_role_vars"]
        self.assertLess(role_vars.index(".advertise_address"), role_vars.index(".node_ip"))
        self.assertLess(role_vars.index(".node_ip"), role_vars.index(".ansible_host"))

        ready = next(
            task for task in agent["post_tasks"] if task.get("name") == "Wait for agent node to report Ready"
        )
        self.assertEqual(ready["delegate_to"], "{{ groups['rke2_servers'] | first }}")
        self.assertEqual(ready["until"], "(_hyops_agent_ready.stdout | trim) == 'True'")

        resolve = next(
            task for task in agent["post_tasks"] if task.get("name") == "Resolve agent Kubernetes node name"
        )
        node_names = resolve["ansible.builtin.set_fact"]["_hyops_agent_node_names"]
        self.assertIn("regex_findall('--hostname-override=([^ ]+)')", node_names)
        self.assertTrue(all(task.get("when") == "not ansible_check_mode" for task in agent["post_tasks"]))

    def test_selected_version_is_promoted_to_both_upstream_roles(self) -> None:
        for play_name in (
            "Platform/onprem/rke2-cluster (server play)",
            "Platform/onprem/rke2-cluster (agent play)",
        ):
            play = self.play(play_name)
            build_vars = next(task for task in play["pre_tasks"] if task.get("name") == "Build role vars")
            version = build_vars["vars"]["_install_rke2_version_raw"]
            promoted = build_vars["ansible.builtin.set_fact"]["_hyops_rke2_role_vars"]

            self.assertIn("rke2_install_version", version)
            self.assertIn("_base_role_vars.get('install_rke2_version'", version)
            self.assertIn("'install_rke2_version': _install_rke2_version_raw", promoted)

    def test_runtime_cleanup_is_opt_in_and_shared_by_serial_plays(self) -> None:
        spec_path = self.root / "modules/platform/onprem/rke2-cluster/spec.yml"
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        self.assertFalse(spec["inputs"]["defaults"]["rke2_upgrade_runtime_cleanup"])

        for play_name, task_name in (
            (
                "Platform/onprem/rke2-cluster (server play)",
                "Prepare clean runtime boundary for server upgrade",
            ),
            (
                "Platform/onprem/rke2-cluster (agent play)",
                "Prepare clean runtime boundary for agent upgrade",
            ),
        ):
            play = self.play(play_name)
            self.assertEqual(play["serial"], 1)
            cleanup = next(task for task in play["pre_tasks"] if task.get("name") == task_name)
            self.assertEqual(cleanup["when"], "rke2_upgrade_runtime_cleanup | bool")
            self.assertEqual(cleanup["ansible.builtin.include_tasks"], "upgrade-runtime-cleanup.yml")

        cleanup_path = (
            self.root
            / "packs/config/ansible/onprem/common/platform/50-rke2-cluster@v1.0/stack"
            / "upgrade-runtime-cleanup.yml"
        )
        cleanup_tasks = yaml.safe_load(cleanup_path.read_text(encoding="utf-8"))
        inspect_binaries = next(
            task for task in cleanup_tasks if task.get("name") == "Inspect installed RKE2 binaries"
        )
        self.assertIn("/usr/bin/rke2", inspect_binaries["loop"])
        self.assertIn("/usr/local/bin/rke2", inspect_binaries["loop"])
        self.assertIn("/opt/rke2/bin/rke2", inspect_binaries["loop"])
        self.assertIn("{{ _hyops_rke2_tarball_dir }}/bin/rke2", inspect_binaries["loop"])

        read_release = next(
            task for task in cleanup_tasks if task.get("name") == "Read installed RKE2 release"
        )
        self.assertNotIn("failed_when", read_release)

        run_cleanup = next(
            task for task in cleanup_tasks if task.get("name") == "Clean the installed RKE2 runtime before upgrade"
        )
        self.assertEqual(
            run_cleanup["ansible.builtin.command"]["argv"],
            ["{{ _hyops_rke2_cleanup_script.stat.path }}"],
        )
        self.assertEqual(run_cleanup["environment"]["RKE2_DATA_DIR"], "{{ _hyops_rke2_data_dir }}")

        check_shims = next(
            task for task in cleanup_tasks if task.get("name") == "Check for remaining RKE2 containerd shims"
        )
        self.assertIn("_hyops_rke2_data_dir | regex_escape", check_shims["ansible.builtin.command"]["argv"][-1])

        verify = next(
            task for task in cleanup_tasks if task.get("name") == "Require old RKE2 containerd shims to be stopped"
        )
        self.assertIn("not ansible_check_mode", verify["when"])

    def test_shipped_rke2_version_pins_are_consistent(self) -> None:
        paths = [
            self.root / "modules/platform/onprem/rke2-cluster/examples/inputs.min.yml",
            self.root / "modules/platform/onprem/rke2-cluster/examples/inputs.typical.yml",
        ]
        versions = {
            yaml.safe_load(path.read_text(encoding="utf-8"))["rke2_install_version"]
            for path in paths
        }

        for relative_path in (
            "blueprints/onprem/rke2@v1/blueprint.yml",
            "blueprints/onprem/rke2-workloads@v1/blueprint.yml",
        ):
            blueprint_path = self.root / relative_path
            blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
            cluster_step = next(step for step in blueprint["steps"] if step["id"] == "rke2_cluster")
            versions.add(cluster_step["inputs"]["rke2_install_version"])

        self.assertEqual(len(versions), 1)
        self.assertRegex(next(iter(versions)), r"^v\d+\.\d+\.\d+\+rke2r\d+$")

    def test_module_requires_operator_selected_stable_release(self) -> None:
        inputs = self.valid_inputs()
        inputs["rke2_install_version"] = ""

        with self.assertRaisesRegex(ValueError, "rke2_install_version"):
            validate(inputs)

        inputs["rke2_install_version"] = "v1.34.12+rke2r1"
        validate(inputs)

    def test_module_retains_legacy_version_input_without_ambiguity(self) -> None:
        inputs = self.valid_inputs()
        inputs["rke2_install_version"] = ""
        inputs["rke2_role_vars"] = {"install_rke2_version": "v1.34.11+rke2r1"}
        validate(inputs)

        inputs["rke2_install_version"] = "v1.34.11+rke2r1"
        validate(inputs)

        inputs["rke2_install_version"] = "v1.34.12+rke2r1"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            validate(inputs)

    def test_module_rejects_non_stable_release_identifiers(self) -> None:
        inputs = self.valid_inputs()
        for version in (
            "1.34.12+rke2r1",
            "v1.34+rke2r1",
            "v1.34.12-rke2r1",
            "v1.34.12+rke2r1-rc1",
            "stable",
        ):
            with self.subTest(version=version):
                inputs["rke2_install_version"] = version
                with self.assertRaisesRegex(ValueError, "explicit stable RKE2 release"):
                    validate(inputs)

    def test_destroy_does_not_require_an_install_release(self) -> None:
        inputs = self.valid_inputs()
        inputs["_hyops_lifecycle_command"] = "destroy"
        inputs["rke2_install_version"] = ""
        inputs["required_env"] = []
        validate(inputs)

    def test_runtime_cleanup_control_requires_a_boolean(self) -> None:
        inputs = self.valid_inputs()
        inputs["rke2_upgrade_runtime_cleanup"] = "true"
        with self.assertRaisesRegex(ValueError, "rke2_upgrade_runtime_cleanup"):
            validate(inputs)
