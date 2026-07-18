from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import yaml


class CloudSqlExternalReplicaDestroyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        core_root = Path(__file__).resolve().parents[5]
        cls.playbook_path = (
            core_root
            / "packs"
            / "config"
            / "ansible"
            / "gcp"
            / "org"
            / "12-cloudsql-external-replica@v1.0"
            / "stack"
            / "destroy.playbook.yml"
        )
        cls.play = yaml.safe_load(cls.playbook_path.read_text(encoding="utf-8"))[0]
        cls.tasks = {task["name"]: task for task in cls.play["tasks"]}

    def test_destroy_uses_input_driven_gcloud_identifiers(self) -> None:
        rendered = self.playbook_path.read_text(encoding="utf-8")

        self.assertIn("{{ migration_job_name }}", rendered)
        self.assertIn("{{ item }}", rendered)
        self.assertIn("--project={{ project_id }}", rendered)
        self.assertIn("--region={{ region }}", rendered)

    def test_destroy_never_force_deletes_cloud_sql(self) -> None:
        delete_tasks = [
            self.tasks["Delete DMS migration job without deleting its Cloud SQL database"],
            self.tasks["Delete remaining DMS connection profiles without deleting Cloud SQL"],
        ]

        for task in delete_tasks:
            argv = task["ansible.builtin.command"]["argv"]
            self.assertNotIn("--force", argv)
            self.assertIn("--quiet", argv)

        outputs = self.tasks["Write HyOps outputs"]["ansible.builtin.copy"]["content"]
        self.assertIn("'cloudsql_database_deleted': false", outputs)

    def test_destroy_orders_job_before_connection_profiles_and_verifies_absence(self) -> None:
        names = [task["name"] for task in self.play["tasks"]]

        self.assertLess(
            names.index("Delete DMS migration job without deleting its Cloud SQL database"),
            names.index("Delete remaining DMS connection profiles without deleting Cloud SQL"),
        )
        self.assertIn("Wait for DMS migration job deletion", names)
        self.assertIn("Verify DMS connection profiles are absent", names)

    def test_missing_objects_are_idempotent(self) -> None:
        delete_tasks = [
            self.tasks["Delete DMS migration job without deleting its Cloud SQL database"],
            self.tasks["Delete remaining DMS connection profiles without deleting Cloud SQL"],
        ]

        for task in delete_tasks:
            conditions = "\n".join(task["failed_when"]).lower()
            self.assertIn("not_found", conditions)
            self.assertIn("does not exist", conditions)

    def test_destroy_executes_and_can_be_rerun_when_objects_are_absent(self) -> None:
        ansible_playbook = shutil.which("ansible-playbook")
        if not ansible_playbook:
            self.skipTest("ansible-playbook is not installed")

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            state_dir = tmp / "fake-dms"
            state_dir.mkdir()
            for name in ("job-1", "destination-1", "source-1"):
                (state_dir / name).touch()

            fake_gcloud = tmp / "gcloud"
            fake_gcloud.write_text(
                """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

args = sys.argv[1:]
state_dir = Path(os.environ["FAKE_DMS_STATE_DIR"])

if args[:1] == ["version"]:
    print("Google Cloud SDK test")
    raise SystemExit(0)
if args[:2] == ["auth", "list"]:
    print("operator@example.com")
    raise SystemExit(0)
if args[:2] == ["projects", "describe"]:
    print(args[2])
    raise SystemExit(0)

kind = ""
action = ""
if args[:3] == ["database-migration", "migration-jobs", "delete"]:
    kind, action = "job", "delete"
elif args[:3] == ["database-migration", "migration-jobs", "describe"]:
    kind, action = "job", "describe"
elif args[:3] == ["database-migration", "connection-profiles", "delete"]:
    kind, action = "profile", "delete"
elif args[:3] == ["database-migration", "connection-profiles", "describe"]:
    kind, action = "profile", "describe"
else:
    print(f"unsupported fake gcloud invocation: {args}", file=sys.stderr)
    raise SystemExit(2)

name = args[3]
resource = state_dir / name
if action == "describe":
    if resource.exists():
        print("{}")
        raise SystemExit(0)
    print("ERROR: NOT_FOUND: resource does not exist", file=sys.stderr)
    raise SystemExit(1)

if resource.exists():
    resource.unlink()
    if kind == "job":
        destination = state_dir / os.environ["FAKE_DMS_DEST_PROFILE"]
        if destination.exists():
            destination.unlink()
    raise SystemExit(0)

print("ERROR: NOT_FOUND: resource does not exist", file=sys.stderr)
raise SystemExit(1)
""",
                encoding="utf-8",
            )
            fake_gcloud.chmod(0o755)

            outputs_file = tmp / "outputs.json"
            runtime_root = tmp / "runtime"
            runtime_root.mkdir()
            home = tmp / "home"
            home.mkdir()

            extra_vars = {
                "hyops_runtime_root": str(runtime_root),
                "hyops_outputs_file": str(outputs_file),
                "project_id": "test-project",
                "region": "test-region",
                "migration_job_name": "job-1",
                "destination_connection_profile_name": "destination-1",
                "source_connection_profile_name": "source-1",
                "gcloud_bin": str(fake_gcloud),
                "gcloud_copy_default_config": False,
                "gcloud_runtime_config_dir": str(tmp / "gcloud-config"),
                "gcloud_active_account": "operator@example.com",
            }
            argv = [
                ansible_playbook,
                "-i",
                "localhost,",
                str(self.playbook_path),
                "--extra-vars",
                json.dumps(extra_vars),
            ]
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["FAKE_DMS_STATE_DIR"] = str(state_dir)
            env["FAKE_DMS_DEST_PROFILE"] = "destination-1"

            first = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, msg=f"{first.stdout}\n{first.stderr}")
            self.assertEqual(list(state_dir.iterdir()), [])
            outputs = json.loads(outputs_file.read_text(encoding="utf-8"))
            self.assertEqual(outputs["cap.db.managed_external_replica"], "destroyed")
            self.assertFalse(outputs["dms_cleanup"]["cloudsql_database_deleted"])

            second = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(second.returncode, 0, msg=f"{second.stdout}\n{second.stderr}")
            self.assertEqual(list(state_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
