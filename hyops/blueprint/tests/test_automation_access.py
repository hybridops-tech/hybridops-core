"""Tests for private lab-device automation access."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml

from hyops.blueprint.automation_access import (
    build_tunnel_ssh_argv,
    linux_tunnel_plan,
    parse_containerlab_inspect,
    parse_dnsmasq_leases,
    prepare_automation_session,
)
from hyops.blueprint.command import (
    _device_process_environment,
    _read_automation_leases,
    run_device,
)
from hyops.blueprint.schema import load_blueprint, validate_blueprint


class AutomationAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.automation = {
            "management_network_label": "Cloud8",
            "management_cidr": "172.29.128.0/24",
            "management_gateway": "172.29.128.1",
            "management_dhcp_range": "172.29.128.50-172.29.128.200",
            "lease_file": "/var/lib/misc/hyops.leases",
            "default_user": "admin",
            "local_socks_port": 0,
        }

    def test_dnsmasq_leases_are_scoped_and_named(self) -> None:
        leases = parse_dnsmasq_leases(
            "\n".join(
                [
                    "1 aa:bb:cc:dd:ee:01 172.29.128.51 r1 *",
                    "2 aa:bb:cc:dd:ee:02 172.29.128.52 * *",
                    "3 aa:bb:cc:dd:ee:03 192.0.2.50 outside *",
                ]
            ),
            "172.29.128.0/24",
            default_user="admin",
        )

        self.assertEqual([item["name"] for item in leases], ["r1", "device-52"])
        self.assertEqual(leases[0]["host"], "172.29.128.51")
        self.assertEqual(leases[0]["source"], "dhcp-lease")

    def test_containerlab_inspect_targets_are_scoped(self) -> None:
        discovered = parse_containerlab_inspect(
            json.dumps(
                {
                    "demo": [
                        {
                            "name": "clab-demo-r1",
                            "kind": "nokia_srlinux",
                            "ipv4_address": "172.20.20.2/24",
                        },
                        {
                            "name": "outside",
                            "kind": "linux",
                            "ipv4_address": "192.0.2.2/24",
                        },
                    ]
                }
            ),
            "172.20.20.0/24",
            default_user="admin",
        )

        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["name"], "clab-demo-r1")
        self.assertEqual(discovered[0]["host"], "172.20.20.2")
        self.assertEqual(discovered[0]["source"], "containerlab-inspect")
        self.assertEqual(discovered[0]["platform"], "nokia_srlinux")

    def test_containerlab_discovery_uses_native_inspect(self) -> None:
        result = SimpleNamespace(returncode=0, stdout='{"demo": []}')
        automation = {
            "discovery_mode": "containerlab-inspect",
            "management_cidr": "172.20.20.0/24",
        }

        with patch(
            "hyops.blueprint.command.subprocess.run",
            return_value=result,
        ) as run:
            output = _read_automation_leases(
                ["ssh", "-F", "/tmp/ssh_config"],
                "gateway",
                automation,
            )

        self.assertEqual(output, result.stdout)
        self.assertEqual(
            run.call_args.args[0][-1],
            "sudo -n containerlab inspect --all -f json",
        )

    def test_session_writes_ssh_vscode_and_inventory_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "gateway-key"
            key.write_text("test", encoding="utf-8")
            key.chmod(0o600)
            paths = SimpleNamespace(root=root, config_dir=root / "config")
            session = prepare_automation_session(
                paths=paths,
                blueprint_ref="gcp/eve-ng@v1",
                env_name="demo-lab",
                automation=self.automation,
                gateway={
                    "host": "127.0.0.1",
                    "user": "opsadmin",
                    "port": 43210,
                    "identity_file": str(key),
                    "known_hosts_file": str(root / "gateway_known_hosts"),
                    "host_key_alias": "hyops-gateway",
                },
                socks_port=1080,
                lease_text="1 aa:bb:cc:dd:ee:01 172.29.128.51 r1 *",
            )

            self.assertEqual(session["aliases"], ["hyops-demo-lab-r1"])
            self.assertIn("ProxyJump hyops-demo-lab-gateway", session["ssh_config"].read_text())
            self.assertIn("r1 ansible_host=hyops-demo-lab-r1", session["inventory"].read_text())
            self.assertIn("socks5h://127.0.0.1:1080", session["proxy_env"].read_text())
            nornir_hosts = yaml.safe_load(session["nornir_hosts"].read_text())
            self.assertEqual(nornir_hosts["r1"]["hostname"], "hyops-demo-lab-r1")
            session_payload = yaml.safe_load(session["session_file"].read_text())
            self.assertEqual(session_payload["socks_proxy"], "socks5h://127.0.0.1:1080")
            environment = _device_process_environment(session)
            self.assertEqual(environment["ANSIBLE_CONFIG"], str(session["ansible_config"]))
            self.assertEqual(
                environment["NORNIR_SSH_CONFIG_FILE"],
                str(session["ssh_config"]),
            )
            self.assertEqual(session["target_file"].stat().st_mode & 0o777, 0o600)
            target_payload = yaml.safe_load(session["target_file"].read_text())
            self.assertEqual(target_payload["targets"][0]["host"], "172.29.128.51")

    def test_target_outside_management_network_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = root / "targets.yml"
            targets.write_text(
                "targets:\n  - name: r1\n    host: 192.0.2.10\n    user: admin\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "outside 172.29.128.0/24"):
                prepare_automation_session(
                    paths=SimpleNamespace(root=root, config_dir=root / "config"),
                    blueprint_ref="gcp/eve-ng@v1",
                    env_name="demo-lab",
                    automation=self.automation,
                    gateway={
                        "host": "127.0.0.1",
                        "user": "opsadmin",
                        "port": 22,
                        "identity_file": str(root / "key"),
                        "known_hosts_file": str(root / "known_hosts"),
                    },
                    socks_port=1080,
                    target_file_override=str(targets),
                )

    def test_dhcp_refresh_updates_address_and_preserves_operator_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "gateway-key"
            key.write_text("test", encoding="utf-8")
            paths = SimpleNamespace(root=root, config_dir=root / "config")
            gateway = {
                "host": "127.0.0.1",
                "user": "opsadmin",
                "port": 43210,
                "identity_file": str(key),
                "known_hosts_file": str(root / "gateway_known_hosts"),
            }
            first = prepare_automation_session(
                paths=paths,
                blueprint_ref="gcp/eve-ng@v1",
                env_name="demo-lab",
                automation=self.automation,
                gateway=gateway,
                socks_port=1080,
                lease_text="1 aa:bb:cc:dd:ee:01 172.29.128.51 r1 *",
            )
            payload = yaml.safe_load(first["target_file"].read_text())
            payload["targets"][0]["name"] = "edge-router"
            payload["targets"][0]["user"] = "netops"
            payload["targets"][0]["platform"] = "ios"
            payload["targets"].append(
                {
                    "name": "static-fw",
                    "host": "172.29.128.80",
                    "user": "admin",
                }
            )
            first["target_file"].write_text(yaml.safe_dump(payload), encoding="utf-8")

            refreshed = prepare_automation_session(
                paths=paths,
                blueprint_ref="gcp/eve-ng@v1",
                env_name="demo-lab",
                automation=self.automation,
                gateway=gateway,
                socks_port=1080,
                lease_text="\n".join(
                    [
                        "2 aa:bb:cc:dd:ee:01 172.29.128.61 r1 *",
                        "2 aa:bb:cc:dd:ee:02 172.29.128.62 r2 *",
                    ]
                ),
            )

            by_name = {item["name"]: item for item in refreshed["targets"]}
            self.assertEqual(by_name["edge-router"]["host"], "172.29.128.61")
            self.assertEqual(by_name["edge-router"]["user"], "netops")
            self.assertEqual(by_name["edge-router"]["platform"], "ios")
            self.assertEqual(by_name["static-fw"]["host"], "172.29.128.80")
            self.assertEqual(by_name["r2"]["source"], "dhcp-lease")
            self.assertEqual(refreshed["new_targets"], ["r2"])

    def test_device_list_shows_default_user_and_port(self) -> None:
        targets = [
            {
                "name": "r1",
                "host": "172.29.128.51",
                "user": "admin",
                "port": 22,
                "source": "dhcp-lease",
                "platform": "ios",
            }
        ]
        ns = SimpleNamespace(device_cmd="list", json=False)
        output = io.StringIO()

        with patch(
            "hyops.blueprint.command._device_context",
            return_value=(self.automation, {}, targets),
        ), redirect_stdout(output):
            rc = run_device(ns)

        self.assertEqual(rc, 0)
        self.assertEqual(
            output.getvalue().strip(),
            "r1  172.29.128.51  user=admin (default)  port=22  ios  DHCP",
        )

    def test_device_edit_opens_and_validates_target_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_file = Path(tmp) / "targets.yml"
            target_file.write_text(
                "version: 1\ntargets:\n  - name: r1\n"
                "    host: 172.29.128.51\n    user: netops\n",
                encoding="utf-8",
            )
            ns = SimpleNamespace(device_cmd="edit", editor="nano")
            result = SimpleNamespace(returncode=0)

            with patch(
                "hyops.blueprint.command._device_material",
                return_value=(self.automation, {"target_file": target_file}),
            ), patch(
                "hyops.blueprint.command._editor_argv",
                return_value=["nano"],
            ), patch(
                "hyops.blueprint.command.subprocess.run",
                return_value=result,
            ) as run:
                rc = run_device(ns)

        self.assertEqual(rc, 0)
        run.assert_called_once_with(["nano", str(target_file)], check=False)

    def test_device_ssh_failure_points_to_target_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ssh_config = root / "ssh_config"
            ssh_config.write_text("Host test\n", encoding="utf-8")
            target_file = root / "targets.yml"
            target = {
                "name": "r1",
                "host": "172.29.128.51",
                "user": "admin",
                "port": 22,
                "identity_file": "",
                "source": "dhcp-lease",
                "platform": "ios",
            }
            material = {
                "ssh_config": ssh_config,
                "target_file": target_file,
                "alias_prefix": "hyops-demo-lab",
            }
            ns = SimpleNamespace(
                device_cmd="ssh",
                target="r1",
                env="demo-lab",
                ref="gcp/eve-ng@v1",
            )
            output = io.StringIO()

            with patch(
                "hyops.blueprint.command._device_context",
                return_value=(self.automation, material, [target]),
            ), patch(
                "hyops.blueprint.command.shutil.which",
                return_value="/usr/bin/ssh",
            ), patch(
                "hyops.blueprint.command.subprocess.run",
                return_value=SimpleNamespace(returncode=255),
            ) as run, redirect_stdout(output):
                rc = run_device(ns)

        self.assertEqual(rc, 255)
        self.assertIn("ERR: device SSH failed for r1 as admin.", output.getvalue())
        self.assertIn(
            "edit: hyops blueprint device edit --env demo-lab --ref gcp/eve-ng@v1",
            output.getvalue(),
        )
        command = run.call_args.args[0]
        self.assertIn("-l", command)
        self.assertIn("admin", command)

    def test_device_web_forwards_target_through_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ssh_config = root / "ssh_config"
            ssh_config.write_text("Host gateway\n", encoding="utf-8")
            target = {
                "name": "f5-ltm",
                "host": "172.29.128.51",
                "user": "admin",
                "port": 22,
                "identity_file": "",
                "source": "static",
                "platform": "f5",
            }
            material = {
                "ssh_config": ssh_config,
                "gateway_alias": "hyops-demo-lab-gateway",
            }
            ns = SimpleNamespace(
                device_cmd="web",
                target="f5-ltm",
                scheme="https",
                port=8443,
                path="/tmui/",
                local_port=10443,
                no_browser=False,
            )
            proc = MagicMock()
            proc.wait.side_effect = KeyboardInterrupt
            proc.poll.return_value = None
            output = io.StringIO()

            with patch(
                "hyops.blueprint.command._device_context",
                return_value=(self.automation, material, [target]),
            ), patch(
                "hyops.blueprint.command.shutil.which",
                return_value="/usr/bin/ssh",
            ), patch(
                "hyops.blueprint.command._available_local_port",
                return_value=10443,
            ), patch(
                "hyops.blueprint.command._require_local_ports_available"
            ), patch(
                "hyops.blueprint.command._wait_for_local_port"
            ), patch(
                "hyops.blueprint.command.subprocess.Popen",
                return_value=proc,
            ) as popen, patch(
                "hyops.blueprint.command.open_operator_url"
            ) as open_url, patch(
                "hyops.blueprint.command._stop_process"
            ) as stop, redirect_stdout(output):
                rc = run_device(ns)

        self.assertEqual(rc, 0)
        command = popen.call_args.args[0]
        self.assertIn("127.0.0.1:10443:172.29.128.51:8443", command)
        self.assertEqual(command[-1], "hyops-demo-lab-gateway")
        open_url.assert_called_once_with("https://127.0.0.1:10443/tmui/")
        stop.assert_called_once_with(proc)
        self.assertIn("device web access: f5-ltm", output.getvalue())
        self.assertIn("device web access closed", output.getvalue())

    def test_device_web_accepts_management_ip_and_does_not_open_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ssh_config = Path(tmp) / "ssh_config"
            ssh_config.write_text("Host gateway\n", encoding="utf-8")
            material = {
                "ssh_config": ssh_config,
                "gateway_alias": "hyops-demo-lab-gateway",
            }
            ns = SimpleNamespace(
                device_cmd="web",
                target="172.29.128.80",
                scheme="http",
                port=0,
                path="/",
                local_port=0,
                no_browser=True,
            )
            proc = MagicMock()
            proc.wait.side_effect = KeyboardInterrupt
            proc.poll.return_value = None

            with patch(
                "hyops.blueprint.command._device_context",
                return_value=(self.automation, material, []),
            ), patch(
                "hyops.blueprint.command.shutil.which",
                return_value="/usr/bin/ssh",
            ), patch(
                "hyops.blueprint.command._available_local_port",
                return_value=18080,
            ), patch(
                "hyops.blueprint.command._require_local_ports_available"
            ), patch(
                "hyops.blueprint.command._wait_for_local_port"
            ), patch(
                "hyops.blueprint.command.subprocess.Popen",
                return_value=proc,
            ) as popen, patch(
                "hyops.blueprint.command.open_operator_url"
            ) as open_url, patch(
                "hyops.blueprint.command._stop_process"
            ):
                rc = run_device(ns)

        self.assertEqual(rc, 0)
        self.assertIn("127.0.0.1:18080:172.29.128.80:80", popen.call_args.args[0])
        open_url.assert_not_called()

    def test_device_web_rejects_invalid_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ssh_config = Path(tmp) / "ssh_config"
            ssh_config.write_text("Host gateway\n", encoding="utf-8")
            ns = SimpleNamespace(
                device_cmd="web",
                target="172.29.128.80",
                scheme="https",
                port=443,
                path="admin",
                local_port=0,
                no_browser=True,
            )
            output = io.StringIO()
            with patch(
                "hyops.blueprint.command._device_context",
                return_value=(
                    self.automation,
                    {"ssh_config": ssh_config, "gateway_alias": "gateway"},
                    [],
                ),
            ), patch(
                "hyops.blueprint.command.shutil.which",
                return_value="/usr/bin/ssh",
            ), redirect_stdout(output):
                rc = run_device(ns)

        self.assertNotEqual(rc, 0)
        self.assertIn("--path must begin with one /", output.getvalue())

    def test_route_command_uses_existing_ssh_boundary(self) -> None:
        plan = linux_tunnel_plan("demo-lab:gcp/eve-ng@v1")
        argv = build_tunnel_ssh_argv(
            gateway={
                "host": "127.0.0.1",
                "user": "opsadmin",
                "ssh_command": ["/usr/bin/ssh", "-p", "40222", "-i", "/tmp/key"],
            },
            plan=plan,
            remote_helper="/usr/local/sbin/hybridops-lab-route",
        )

        self.assertEqual(argv[0], "/usr/bin/ssh")
        self.assertIn("Tunnel=point-to-point", argv)
        self.assertEqual(argv[argv.index("-w") + 1], f"{plan['tunnel_id']}:{plan['tunnel_id']}")
        self.assertIn("opsadmin@127.0.0.1", argv)
        self.assertIn("/usr/local/sbin/hybridops-lab-route", argv[-1])
        self.assertIn(plan["remote_cidr"], argv[-1])

    def test_tunnel_plan_is_stable_and_link_local(self) -> None:
        first = linux_tunnel_plan("demo-lab:gcp/eve-ng@v1")
        second = linux_tunnel_plan("demo-lab:gcp/eve-ng@v1")

        self.assertEqual(first, second)
        self.assertGreaterEqual(first["tunnel_id"], 100)
        self.assertLessEqual(first["tunnel_id"], 899)
        self.assertTrue(first["local_ip"].startswith("169.254."))
        self.assertTrue(first["remote_ip"].startswith("169.254."))

    def test_schema_rejects_gateway_outside_management_network(self) -> None:
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "eve-ng@v1" / "blueprint.yml"
        payload = load_blueprint(path)
        payload["access"]["automation"]["management_gateway"] = "192.0.2.1"

        with self.assertRaisesRegex(ValueError, "must be inside management_cidr"):
            validate_blueprint(payload, path)

    def test_schema_requires_absolute_remote_lease_path(self) -> None:
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "eve-ng@v1" / "blueprint.yml"
        payload = load_blueprint(path)
        payload["access"]["automation"]["lease_file"] = "dnsmasq.leases"

        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            validate_blueprint(payload, path)

    def test_schema_rejects_management_dhcp_range_outside_network(self) -> None:
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "eve-ng@v1" / "blueprint.yml"
        payload = load_blueprint(path)
        payload["access"]["automation"]["management_dhcp_range"] = (
            "192.0.2.50-192.0.2.100"
        )

        with self.assertRaisesRegex(ValueError, "usable range inside"):
            validate_blueprint(payload, path)


if __name__ == "__main__":
    unittest.main()
