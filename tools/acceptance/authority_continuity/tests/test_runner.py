from __future__ import annotations

import io
import json
import runpy
import signal
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, call, patch

import yaml

from hyops.runtime.exitcodes import OPERATOR_ERROR
from tools.acceptance.authority_continuity.runner import (
    _FIXTURE_ROOT,
    _MANIFEST,
    _PINNED_KIND_IMAGE,
    AuthorityContinuityBenchmarkError,
    ClusterCreateError,
    _blueprint_payload,
    _create_cluster,
    _delete_cluster,
    _prepare_output_root,
    _print_text_report,
    _render_html,
    _source_identity,
    _terminate_process,
    _validate_result,
    _write_json_atomic,
    build_parser,
    run_benchmark,
)


def _interval(status: str, decision: str, before: str, after: str) -> dict:
    return {
        "interval_status": status,
        "completion_status": "fresh",
        "decision": decision,
        "before": {"token": f"resourceVersion:{before}"},
        "after": {"token": f"resourceVersion:{after}"},
    }


def _deploy(
    interval: dict,
    *,
    status: str = "failed",
    rc: int = OPERATOR_ERROR,
    module_rc: int = 0,
) -> dict:
    return {
        "steps": [
            {
                "id": "observed_operation",
                "status": status,
                "rc": rc,
                "module_rc": module_rc,
                "authority_interval": interval,
            }
        ]
    }


class AuthorityContinuityBenchmarkTest(TestCase):
    def test_blueprint_uses_strict_kubernetes_authority_contract(self) -> None:
        payload = _blueprint_payload(Path("/tmp/benchmark-barrier"), "run-42", 60)

        authority = payload["authorities"]["change_control"]
        step = payload["steps"][0]
        contracts = step["contracts"]
        self.assertEqual(authority["provider"], "kubernetes")
        self.assertEqual(authority["capability"], "resource_authority")
        self.assertNotIn("token", authority["config"])
        self.assertEqual(step["module_ref"], "acceptance/core/authority-window")
        module_spec = (
            _FIXTURE_ROOT
            / "modules"
            / "acceptance"
            / "core"
            / "authority-window"
            / "spec.yml"
        )
        self.assertEqual(
            yaml.safe_load(module_spec.read_text())["module_ref"], step["module_ref"]
        )
        self.assertEqual(
            contracts["authority_observation"],
            {"expected_change": "none", "on_unverifiable": "fail"},
        )

    def test_manifest_limits_authority_reader_to_one_get(self) -> None:
        documents = list(yaml.safe_load_all(_MANIFEST))
        role = next(item for item in documents if item.get("kind") == "Role")

        self.assertEqual(
            role["rules"],
            [
                {
                    "apiGroups": [""],
                    "resources": ["configmaps"],
                    "resourceNames": ["change-authority"],
                    "verbs": ["get"],
                }
            ],
        )

    def test_reconverged_data_is_denied_despite_matching_final_snapshot(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "mutated", "resource_version": "11", "data": {"owner": "manual"}},
            {
                "stage": "restored",
                "resource_version": "12",
                "data": {"owner": "gitops"},
            },
            {"stage": "final", "resource_version": "12", "data": {"owner": "gitops"}},
        ]

        result = _validate_result(
            "reconverged",
            OPERATOR_ERROR,
            snapshots,
            _deploy(_interval("drifted", "deny", "10", "12")),
        )

        self.assertTrue(result["passed"])
        self.assertTrue(result["final_data_matches_initial"])
        self.assertEqual(result["authority_interval"]["decision"], "deny")

    def test_result_requires_mutated_owner_value(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "mutated", "resource_version": "11", "data": {"owner": "gitops"}},
            {
                "stage": "restored",
                "resource_version": "12",
                "data": {"owner": "gitops"},
            },
            {"stage": "final", "resource_version": "12", "data": {"owner": "gitops"}},
        ]

        result = _validate_result(
            "reconverged",
            OPERATOR_ERROR,
            snapshots,
            _deploy(_interval("drifted", "deny", "10", "12")),
        )

        self.assertFalse(result["passed"])
        self.assertEqual(
            [name for name, passed in result["checks"].items() if not passed],
            ["mutated_owner"],
        )

    def test_result_rejects_denial_after_module_timeout(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "mutated", "resource_version": "11", "data": {"owner": "manual"}},
            {"stage": "final", "resource_version": "11", "data": {"owner": "manual"}},
        ]

        result = _validate_result(
            "persistent",
            OPERATOR_ERROR,
            snapshots,
            _deploy(
                _interval("drifted", "deny", "10", "11"),
                module_rc=OPERATOR_ERROR,
            ),
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["module_exit_code"])

    def test_result_accepts_denial_after_successful_module(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "mutated", "resource_version": "11", "data": {"owner": "manual"}},
            {"stage": "final", "resource_version": "11", "data": {"owner": "manual"}},
        ]

        result = _validate_result(
            "persistent",
            OPERATOR_ERROR,
            snapshots,
            _deploy(_interval("drifted", "deny", "10", "11")),
        )

        self.assertTrue(result["passed"])

    def test_result_fails_when_receipt_revision_does_not_match_snapshot(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "final", "resource_version": "10", "data": {"owner": "gitops"}},
        ]

        result = _validate_result(
            "stable",
            0,
            snapshots,
            _deploy(_interval("stable", "allow", "9", "10"), status="ok", rc=0),
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["before_revision"])

    def test_stable_result_requires_fresh_completion(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "final", "resource_version": "10", "data": {"owner": "gitops"}},
        ]
        interval = _interval("stable", "allow", "10", "10")
        interval["completion_status"] = "stale"

        result = _validate_result(
            "stable",
            0,
            snapshots,
            _deploy(interval, status="ok", rc=0),
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["completion_status"])

    def test_stable_result_requires_revision_continuity(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {"stage": "final", "resource_version": "11", "data": {"owner": "gitops"}},
        ]

        result = _validate_result(
            "stable",
            0,
            snapshots,
            _deploy(
                _interval("stable", "allow", "10", "11"),
                status="ok",
                rc=0,
            ),
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["stable_revision_continuity"])

    def test_result_fails_when_scenario_snapshot_sequence_is_incomplete(self) -> None:
        snapshots = [
            {"stage": "initial", "resource_version": "10", "data": {"owner": "gitops"}},
            {
                "stage": "restored",
                "resource_version": "12",
                "data": {"owner": "gitops"},
            },
            {"stage": "final", "resource_version": "12", "data": {"owner": "gitops"}},
        ]

        result = _validate_result(
            "reconverged",
            OPERATOR_ERROR,
            snapshots,
            _deploy(_interval("drifted", "deny", "10", "12")),
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["snapshot_stages"])

    def test_html_report_escapes_runtime_values(self) -> None:
        report = {
            "result": "passed<script>",
            "generated_at": "2026-11-21T12:00:00Z",
            "cluster": {"kubernetes_version": "v1.34.0"},
            "scenarios": [],
        }

        rendered = _render_html(report)

        self.assertIn("passed&lt;script&gt;", rendered)
        self.assertNotIn("passed<script>", rendered)

    def test_text_report_handles_missing_interval_fields(self) -> None:
        output = io.StringIO()
        report = {
            "result": "failed",
            "scenarios": [
                {
                    "scenario": "stable",
                    "authority_interval": {},
                    "final_data_matches_initial": True,
                }
            ],
        }

        with redirect_stdout(output):
            _print_text_report(report, Path("/tmp/report"))

        self.assertIn("interval=missing decision=missing", output.getvalue())

    def test_output_directory_rejects_symbolic_link(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            link = root / "results"
            link.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(
                AuthorityContinuityBenchmarkError,
                "must not be a symbolic link",
            ):
                _prepare_output_root(str(link))

    def test_output_directory_must_be_new(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "results"
            output.mkdir()

            with self.assertRaisesRegex(
                AuthorityContinuityBenchmarkError,
                "already exists",
            ):
                _prepare_output_root(str(output))

    def test_output_directory_must_be_outside_source_checkout(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "results"

            with self.assertRaisesRegex(
                AuthorityContinuityBenchmarkError,
                "outside the source checkout",
            ):
                _prepare_output_root(str(output), forbidden_root=root)

            self.assertFalse(output.exists())

    def test_failed_kind_creation_removes_a_partial_cluster(self) -> None:
        failure = AuthorityContinuityBenchmarkError("kind failed")
        kubeconfig = Path("/tmp/authority-test-kubeconfig")
        with (
            patch(
                "tools.acceptance.authority_continuity.runner._kind_clusters",
                side_effect=[set(), {"authority-test"}],
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._run",
                side_effect=failure,
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._delete_cluster"
            ) as delete,
            self.assertRaisesRegex(ClusterCreateError, "kind failed") as raised,
        ):
            _create_cluster(
                "authority-test",
                kubeconfig,
                "",
            )

        self.assertEqual(raised.exception.cleanup_status, "removed")
        delete.assert_called_once_with("authority-test", kubeconfig)

    def test_failed_kind_creation_without_cluster_needs_no_cleanup(self) -> None:
        failure = AuthorityContinuityBenchmarkError("kind failed")
        with (
            patch(
                "tools.acceptance.authority_continuity.runner._kind_clusters",
                side_effect=[set(), set()],
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._run",
                side_effect=failure,
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._delete_cluster"
            ) as delete,
            self.assertRaisesRegex(ClusterCreateError, "kind failed") as raised,
        ):
            _create_cluster(
                "authority-test",
                Path("/tmp/authority-test-kubeconfig"),
                "",
            )

        self.assertEqual(raised.exception.cleanup_status, "not-created")
        delete.assert_not_called()

    def test_failed_kind_creation_reports_cleanup_failure(self) -> None:
        create_failure = AuthorityContinuityBenchmarkError("kind failed")
        cleanup_failure = AuthorityContinuityBenchmarkError("delete failed")
        with (
            patch(
                "tools.acceptance.authority_continuity.runner._kind_clusters",
                side_effect=[set(), {"authority-test"}],
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._run",
                side_effect=create_failure,
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._delete_cluster",
                side_effect=cleanup_failure,
            ),
            self.assertRaisesRegex(
                ClusterCreateError,
                "partial-cluster cleanup failed: delete failed",
            ) as raised,
        ):
            _create_cluster(
                "authority-test",
                Path("/tmp/authority-test-kubeconfig"),
                "",
            )

        self.assertEqual(raised.exception.cleanup_status, "failed")

    def test_cluster_deletion_uses_private_kubeconfig(self) -> None:
        kubeconfig = Path("/tmp/authority-test-kubeconfig")
        with patch("tools.acceptance.authority_continuity.runner._run") as run:
            _delete_cluster("authority-test", kubeconfig)

        run.assert_called_once_with(
            [
                "kind",
                "delete",
                "cluster",
                "--name",
                "authority-test",
                "--kubeconfig",
                str(kubeconfig),
            ],
            timeout_s=180,
        )

    def test_process_termination_escalates_to_kill(self) -> None:
        process = Mock()
        process.pid = 1234
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["hyops"], 10),
            ("", ""),
        ]

        with patch(
            "tools.acceptance.authority_continuity.runner.os.killpg"
        ) as kill_group:
            _terminate_process(process)

        self.assertEqual(
            kill_group.call_args_list,
            [call(1234, signal.SIGTERM), call(1234, signal.SIGKILL)],
        )

    def test_default_kind_image_is_digest_pinned(self) -> None:
        namespace = build_parser().parse_args([])

        self.assertEqual(namespace.kind_image, _PINNED_KIND_IMAGE)
        self.assertRegex(namespace.kind_image, r"@sha256:[0-9a-f]{64}$")

    def test_source_identity_changes_with_untracked_content(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(
                ["git", "init", "-q", "--template=", str(root)],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"],
                check=True,
            )
            rejecting_hooks = root / "rejecting-hooks"
            rejecting_hooks.mkdir()
            pre_commit = rejecting_hooks / "pre-commit"
            pre_commit.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            pre_commit.chmod(0o755)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "core.hooksPath",
                    str(rejecting_hooks),
                ],
                check=True,
            )
            empty_hooks = root / "empty-hooks"
            empty_hooks.mkdir()
            (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
            (root / ".git" / "info" / "exclude").write_text(
                "rejecting-hooks/\nempty-hooks/\n",
                encoding="utf-8",
            )
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    f"core.hooksPath={empty_hooks}",
                    "-C",
                    str(root),
                    "commit",
                    "--no-gpg-sign",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            clean = _source_identity(root)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "status.showUntrackedFiles",
                    "no",
                ],
                check=True,
            )
            (root / "untracked.txt").write_text("first\n", encoding="utf-8")
            first = _source_identity(root)
            (root / "untracked.txt").write_text("second\n", encoding="utf-8")
            second = _source_identity(root)
            (root / "tracked.txt").chmod(0o755)
            executable = _source_identity(root)
            carriage_path = root / "carriage\rreturn.txt"
            carriage_path.write_text("first\n", encoding="utf-8")
            carriage_first = _source_identity(root)
            carriage_path.write_text("second\n", encoding="utf-8")
            carriage_second = _source_identity(root)

        self.assertFalse(clean["git_dirty"])
        self.assertTrue(first["git_dirty"])
        self.assertNotEqual(clean["source_tree_sha256"], first["source_tree_sha256"])
        self.assertNotEqual(first["source_tree_sha256"], second["source_tree_sha256"])
        self.assertNotEqual(
            second["source_tree_sha256"], executable["source_tree_sha256"]
        )
        self.assertNotEqual(
            carriage_first["source_tree_sha256"],
            carriage_second["source_tree_sha256"],
        )

    def test_partial_cluster_cleanup_failure_is_recorded(self) -> None:
        source = {
            "version": "0.1.6",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "source_tree_sha256": "b" * 64,
            "source_file_count": 10,
        }
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            namespace = build_parser().parse_args(
                ["--scenario", "stable", "--out-dir", str(output)]
            )
            with (
                patch("tools.acceptance.authority_continuity.runner._require_tools"),
                patch(
                    "tools.acceptance.authority_continuity.runner._source_identity",
                    return_value=source,
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._tool_versions",
                    return_value={"kind": "kind v0.31.0"},
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._create_cluster",
                    side_effect=ClusterCreateError(
                        "kind create failed and partial-cluster cleanup failed",
                        cleanup_status="failed",
                    ),
                ),
            ):
                result = run_benchmark(namespace)

            report = json.loads((output / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertEqual(report["result"], "failed")
        self.assertEqual(report["cluster"]["cleanup"], "failed")

    def test_cleanup_failure_fails_benchmark_and_report(self) -> None:
        def kubectl(_kubeconfig, *arguments, input_text=None):
            del input_text
            if arguments[:2] == ("create", "token"):
                return "fixture-token"
            if arguments[:2] == ("version", "--output"):
                return json.dumps({"serverVersion": {"gitVersion": "v1.35.0"}})
            return ""

        scenario_result = {
            "scenario": "stable",
            "passed": True,
            "final_data_matches_initial": True,
            "snapshots": [],
            "authority_interval": {
                "interval_status": "stable",
                "decision": "allow",
            },
        }
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            namespace = build_parser().parse_args(
                [
                    "--scenario",
                    "stable",
                    "--out-dir",
                    str(output),
                    "--allow-dirty-source",
                ]
            )
            with (
                patch("tools.acceptance.authority_continuity.runner._require_tools"),
                patch(
                    "tools.acceptance.authority_continuity.runner._source_identity",
                    return_value={
                        "version": "0.1.6",
                        "git_sha": "a" * 40,
                        "git_dirty": True,
                        "source_tree_sha256": "b" * 64,
                        "source_file_count": 10,
                    },
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._tool_versions",
                    return_value={"kind": "kind v0.30.0"},
                ),
                patch("tools.acceptance.authority_continuity.runner._create_cluster"),
                patch(
                    "tools.acceptance.authority_continuity.runner._kubectl",
                    side_effect=kubectl,
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._cluster_connection",
                    return_value=("https://127.0.0.1:6443", "/tmp/ca.crt"),
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._run_scenario",
                    return_value=scenario_result,
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._delete_cluster",
                    side_effect=AuthorityContinuityBenchmarkError("delete failed"),
                ),
            ):
                result = run_benchmark(namespace)

            report = json.loads((output / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertEqual(report["result"], "failed")
        self.assertEqual(report["cluster"]["cleanup"], "failed")

    def test_source_change_during_run_fails_benchmark(self) -> None:
        def kubectl(_kubeconfig, *arguments, input_text=None):
            del input_text
            if arguments[:2] == ("create", "token"):
                return "fixture-token"
            if arguments[:2] == ("version", "--output"):
                return json.dumps({"serverVersion": {"gitVersion": "v1.35.0"}})
            return ""

        source = {
            "version": "0.1.6",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "source_tree_sha256": "b" * 64,
            "source_file_count": 10,
        }
        changed_source = {**source, "source_tree_sha256": "c" * 64}
        scenario_result = {
            "scenario": "stable",
            "passed": True,
            "final_data_matches_initial": True,
            "snapshots": [],
            "authority_interval": {
                "interval_status": "stable",
                "decision": "allow",
            },
        }
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            namespace = build_parser().parse_args(
                ["--scenario", "stable", "--out-dir", str(output)]
            )
            with (
                patch("tools.acceptance.authority_continuity.runner._require_tools"),
                patch(
                    "tools.acceptance.authority_continuity.runner._source_identity",
                    side_effect=[source, changed_source],
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._tool_versions",
                    return_value={"kind": "kind v0.31.0"},
                ),
                patch("tools.acceptance.authority_continuity.runner._create_cluster"),
                patch(
                    "tools.acceptance.authority_continuity.runner._kubectl",
                    side_effect=kubectl,
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._cluster_connection",
                    return_value=("https://127.0.0.1:6443", "/tmp/ca.crt"),
                ),
                patch(
                    "tools.acceptance.authority_continuity.runner._run_scenario",
                    return_value=scenario_result,
                ),
                patch("tools.acceptance.authority_continuity.runner._delete_cluster"),
            ):
                result = run_benchmark(namespace)

            report = json.loads((output / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertEqual(report["result"], "failed")
        self.assertNotIn("verified_after", report["source"])

    def test_dirty_source_is_rejected_before_cluster_creation(self) -> None:
        namespace = build_parser().parse_args(["--scenario", "stable"])
        stderr = io.StringIO()

        with (
            patch("tools.acceptance.authority_continuity.runner._require_tools"),
            patch(
                "tools.acceptance.authority_continuity.runner._source_identity",
                return_value={"git_dirty": True},
            ),
            patch(
                "tools.acceptance.authority_continuity.runner._tool_versions"
            ) as tool_versions,
            patch(
                "tools.acceptance.authority_continuity.runner._create_cluster"
            ) as create_cluster,
            redirect_stderr(stderr),
        ):
            result = run_benchmark(namespace)

        self.assertEqual(result, OPERATOR_ERROR)
        self.assertIn("source tree has uncommitted changes", stderr.getvalue())
        tool_versions.assert_not_called()
        create_cluster.assert_not_called()

    def test_operation_window_releases_only_for_matching_nonce(self) -> None:
        script = (
            _FIXTURE_ROOT
            / "packs"
            / "iac"
            / "terragrunt"
            / "authority-window"
            / "stack"
            / "modules"
            / "window"
            / "window.py"
        )
        release_matches = runpy.run_path(str(script))["_release_matches"]
        with TemporaryDirectory() as temporary:
            barrier = Path(temporary)
            request = json.dumps(
                {"barrier_dir": str(barrier), "run_nonce": "test-run", "timeout_s": 5}
            )
            process = subprocess.Popen(
                [sys.executable, str(script), request],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                marker = barrier / "window-open.json"
                deadline = time.monotonic() + 3
                while not marker.is_file() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.is_file())
                release = barrier / "window-release.json"
                _write_json_atomic(release, {"run_nonce": "different-run"})
                self.assertFalse(release_matches(release, "test-run"))
                time.sleep(0.2)
                self.assertIsNone(process.poll())
                _write_json_atomic(release, {"run_nonce": "test-run"})
                stdout, stderr = process.communicate(timeout=5)
            finally:
                if process.poll() is None:
                    _terminate_process(process)

            self.assertEqual(process.returncode, 0, msg=stderr or stdout)


if __name__ == "__main__":
    import unittest

    unittest.main()
