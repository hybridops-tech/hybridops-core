import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.commands._apply_helpers import merge_template_image_outputs
from hyops.drivers.images.packer.driver import run
from hyops.drivers.images.packer.provenance import (
    build_template_manifest,
    lookup_packer_version,
    parse_packer_version,
    public_source_url,
    retained_provenance,
    write_template_manifest,
)
from hyops.runtime.proc import ProcResult
from hyops.runtime.state import write_json_atomic


def _manifest(template_key: str, source_url: str, checksum: str) -> dict:
    return build_template_manifest(
        run_id="build-9",
        template_key=template_key,
        template_name=f"{template_key}-template",
        vmid=9001,
        source_url=source_url,
        source_checksum=checksum,
        profile="onprem-proxmox@v1.0",
        pack_id="onprem/proxmox/images/00-template-image@v1.0",
        builder_version="1.11.2",
    )


class TemplateProvenanceTests(unittest.TestCase):
    def test_linux_and_windows_manifests_share_one_shape(self) -> None:
        linux = _manifest(
            "ubuntu-24.04",
            "https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso",
            "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b",
        )
        windows = _manifest(
            "windows-11-enterprise",
            "https://user:token@software.download.example/dbazure/windows.iso?sig=secret#frag",
            "sha256:a61adeab895ef5a4db436e0a7011c92a2ff17bb0357f58b13bbc4062e535e7b9",
        )
        self.assertEqual(set(linux), set(windows))
        self.assertEqual(linux["schema_version"], 1)
        self.assertEqual(linux["source_filename"], "ubuntu-24.04.3-live-server-amd64.iso")
        self.assertEqual(windows["source_filename"], "windows.iso")
        self.assertEqual(
            windows["source_url"],
            "https://software.download.example/dbazure/windows.iso",
        )
        rendered = json.dumps(windows)
        self.assertNotIn("token", rendered)
        self.assertNotIn("sig=", rendered)
        self.assertNotIn("proxmox_token_secret", rendered)

    def test_signed_url_drops_user_query_and_fragment(self) -> None:
        self.assertEqual(
            public_source_url("https://cdn.example:8443/iso/ubuntu.iso?X-Amz-Signature=abc#part"),
            "https://cdn.example:8443/iso/ubuntu.iso",
        )
        self.assertIsNone(public_source_url("/var/lib/iso/ubuntu.iso"))
        self.assertIsNone(public_source_url("not a url"))

    def test_unreadable_packer_version_is_null(self) -> None:
        self.assertEqual(parse_packer_version("Packer v1.11.2\n"), "1.11.2")
        self.assertIsNone(parse_packer_version("packer: command not found"))
        manifest = build_template_manifest(
            run_id="build-9",
            template_key="ubuntu-24.04",
            template_name="ubuntu-24.04-template",
            vmid=9001,
            source_url="https://example.test/ubuntu.iso",
            source_checksum="sha256:abc",
            profile="onprem-proxmox@v1.0",
            pack_id="pack",
            builder_version=None,
        )
        self.assertIsNone(manifest["builder_version"])

    def test_missing_packer_version_warns(self) -> None:
        version, warning = lookup_packer_version("/bin/false")
        self.assertIsNone(version)
        self.assertIn("builder_version", warning)

    def test_local_iso_keeps_the_filename(self) -> None:
        manifest = _manifest(
            "ubuntu-24.04",
            "/var/lib/vz/template/iso/ubuntu-24.04.3-live-server-amd64.iso",
            "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b",
        )
        self.assertIsNone(manifest["source_url"])
        self.assertEqual(manifest["source_filename"], "ubuntu-24.04.3-live-server-amd64.iso")
        self.assertTrue(manifest["source_checksum"].startswith("sha256:"))

    def test_manifest_file_mode_is_restricted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_template_manifest(Path(tmp), _manifest("ubuntu-24.04", "https://example.test/a.iso", "sha256:abc"))
            mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_rebuild_replaces_identity_and_skip_keeps_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            module_ref = "core/onprem/template-image"
            previous = {
                "status": "ok",
                "outputs": {
                    "template_vm_ids": {"ubuntu-24.04": 100},
                    "templates": {
                        "ubuntu-24.04": {
                            "vm_id": 100,
                            "name": "ubuntu-24.04-template",
                            "source_checksum": "sha256:old",
                            "build_run_id": "run-old",
                        },
                        "rocky-9": {"vm_id": 101, "name": "rocky-9-template"},
                    },
                },
            }
            write_json_atomic(state_dir / "modules" / "core__onprem__template-image" / "latest.json", previous)

            rebuilt = merge_template_image_outputs(
                state_dir,
                module_ref,
                {
                    "template_vm_ids": {"ubuntu-24.04": 100},
                    "templates": {
                        "ubuntu-24.04": {
                            "vm_id": 100,
                            "name": "ubuntu-24.04-template",
                            "source_checksum": "sha256:new",
                            "build_run_id": "run-new",
                        }
                    },
                },
            )
            self.assertEqual(rebuilt["templates"]["ubuntu-24.04"]["source_checksum"], "sha256:new")
            self.assertEqual(rebuilt["templates"]["ubuntu-24.04"]["build_run_id"], "run-new")
            self.assertNotIn("source_checksum", rebuilt["templates"]["rocky-9"])

            skipped = merge_template_image_outputs(
                state_dir,
                module_ref,
                {
                    "template_vm_ids": {"ubuntu-24.04": 100},
                    "templates": {
                        "ubuntu-24.04": {
                            "vm_id": 100,
                            "name": "ubuntu-24.04-template",
                            **retained_provenance(previous["outputs"]["templates"]["ubuntu-24.04"]),
                        }
                    },
                },
            )
            self.assertEqual(skipped["templates"]["ubuntu-24.04"]["source_checksum"], "sha256:old")
            self.assertEqual(skipped["templates"]["ubuntu-24.04"]["build_run_id"], "run-old")
            self.assertNotIn("sha256:current-pack", json.dumps(skipped))

    def test_legacy_state_is_not_filled_from_the_current_pack(self) -> None:
        self.assertEqual(retained_provenance({"vm_id": 100, "name": "old"}), {})


class TemplateProvenanceDriverTests(unittest.TestCase):
    def _request(self, root: Path, *, command: str = "preflight") -> dict:
        credentials_dir = root / "credentials"
        credentials_dir.mkdir(parents=True)
        (credentials_dir / "proxmox.credentials.tfvars").write_text(
            "\n".join(
                [
                    'proxmox_url = "https://pve.example:8006/api2/json"',
                    'proxmox_token_id = "automation@pam!infra-token"',
                    'proxmox_token_secret = "secret-token-value"',
                    'proxmox_node = "pve"',
                    'storage_pool = "local-lvm"',
                    'storage_iso = "local"',
                    'network_bridge = "vmbr0"',
                    'http_bind_address = "127.0.0.1"',
                    "http_port = 8802",
                    'ssh_public_key = "ssh-ed25519 test"',
                ]
            ),
            encoding="utf-8",
        )
        return {
            "run_id": "build-9",
            "command": command,
            "module_ref": "core/onprem/template-image",
            "state_instance": "",
            "inputs": {
                "template_key": "ubuntu-24.04",
                "vmid": 981001,
                "name": "ubuntu-test",
                "post_build_smoke": {"enabled": False},
            },
            "execution": {
                "driver": "images/packer",
                "profile": "onprem-proxmox@v1.0",
                "pack_id": "onprem/proxmox/images/00-template-image@v1.0",
            },
            "runtime": {
                "root": str(root),
                "env": "test",
                "work_dir": str(root / "work"),
                "credentials_dir": str(credentials_dir),
                "state_dir": str(root / "state"),
            },
            "evidence_dir": str(root / "evidence"),
        }

    def _pack_stack(self):
        from types import SimpleNamespace

        repo_root = Path(__file__).resolve().parents[5]
        return SimpleNamespace(
            stack_dir=(
                repo_root
                / "packs/images/packer/onprem/proxmox/images/00-template-image@v1.0/stack"
            )
        )

    @patch("hyops.drivers.images.packer.driver._proxmox_installer_delivery_error", return_value="")
    @patch("hyops.drivers.images.packer.driver._validate_proxmox_build_readiness", return_value="")
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_is_template", return_value=(True, ""))
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_exists", return_value=(True, ""))
    @patch("hyops.drivers.images.packer.driver.resolve_pack_stack")
    @patch("hyops.drivers.images.packer.driver.shutil.which", return_value="/usr/bin/packer")
    def test_skip_keeps_known_provenance_and_writes_no_manifest(
        self,
        _which,
        resolve_pack,
        _exists,
        _is_template,
        _readiness,
        _delivery,
    ):
        resolve_pack.return_value = self._pack_stack()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state" / "modules" / "core__onprem__template-image" / "latest.json"
            write_json_atomic(
                state_path,
                {
                    "outputs": {
                        "templates": {
                            "ubuntu-24.04": {
                                "vm_id": 981001,
                                "name": "ubuntu-test",
                                "source_checksum": "sha256:old",
                                "build_run_id": "run-old",
                            }
                        }
                    }
                },
            )
            result = run(self._request(root))
            record = result["normalized_outputs"]["published_outputs"]["templates"]["ubuntu-24.04"]
            self.assertEqual(record["source_checksum"], "sha256:old")
            self.assertEqual(record["build_run_id"], "run-old")
            self.assertFalse((root / "evidence" / "template_manifest.json").exists())

    @patch("hyops.drivers.images.packer.driver._lookup_packer_version", return_value=("1.11.2", ""))
    @patch("hyops.drivers.images.packer.driver.run_capture_stream")
    @patch("hyops.drivers.images.packer.driver._proxmox_installer_delivery_error", return_value="")
    @patch("hyops.drivers.images.packer.driver._validate_proxmox_build_readiness", return_value="")
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_exists", return_value=(False, ""))
    @patch("hyops.drivers.images.packer.driver.resolve_pack_stack")
    @patch("hyops.drivers.images.packer.driver.shutil.which", return_value="/usr/bin/packer")
    def test_completed_build_writes_manifest_before_smoke(
        self,
        _which,
        resolve_pack,
        _exists,
        _readiness,
        _delivery,
        run_capture,
        _version,
    ):
        resolve_pack.return_value = self._pack_stack()
        run_capture.return_value = ProcResult(
            argv=["packer"],
            cwd=None,
            rc=0,
            duration_ms=1,
            stdout="",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(self._request(root, command="apply"))
            self.assertEqual(result["status"], "ok", result)
            manifest_path = root / "evidence" / "template_manifest.json"
            self.assertTrue(manifest_path.is_file(), result)
            self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            text = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-token-value", text)
            self.assertEqual(manifest["builder_version"], "1.11.2")
            self.assertEqual(manifest["run_id"], "build-9")
            self.assertTrue(str(manifest["source_checksum"]).startswith("sha256:"))
            record = result["normalized_outputs"]["published_outputs"]["templates"]["ubuntu-24.04"]
            self.assertEqual(record["source_checksum"], manifest["source_checksum"])
            self.assertEqual(record["build_run_id"], "build-9")
            self.assertEqual(record["vm_id"], 981001)
            self.assertEqual(result["normalized_outputs"]["post_build_smoke"]["status"], "skipped")
        self.assertGreaterEqual(run_capture.call_count, 1)
