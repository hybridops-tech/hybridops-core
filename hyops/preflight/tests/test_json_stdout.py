"""Regression tests for preflight JSON stdout."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from hyops.cli import build_parser
from hyops.preflight.command import run


REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "hyops.cli", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class PreflightJsonStdoutTests(unittest.TestCase):
    def test_passing_json_stdout_is_one_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run("preflight", "--root", tmp, "--json")
            payload = self._assert_json_document(result)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["code"], 0)

    def test_failing_json_stdout_is_one_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run("preflight", "--root", tmp, "--target", "gcp", "--json")
            payload = self._assert_json_document(result)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], result.returncode)
        names = [item["name"] for item in payload["results"]]
        self.assertIn("readiness:gcp", names)

    def test_text_mode_still_announces_the_run_record_on_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run("preflight", "--root", tmp, "--target", "gcp")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("readiness:gcp", result.stdout)
            self.assertIn("run record:", result.stdout)
            self.assertNotIn("run record:", result.stderr)
            record = result.stdout.split("run record:", 1)[1].strip()
            log = Path(record) / "output.log"
            self.assertTrue(log.is_file(), result.stdout)
            self.assertIn("readiness:gcp", log.read_text(encoding="utf-8"))

    def test_module_diagnostics_do_not_corrupt_json(self) -> None:
        for status in ("ok", "error", "exception"):
            with self.subTest(status=status):
                code, stdout, stderr = self._run_noisy_module(status, json_mode=True)
                payload = json.loads(stdout)
                self.assertEqual(payload["ok"], status == "ok")
                self.assertEqual(payload["code"], code)
                self.assertEqual(code == 0, status == "ok")
                self.assertIn("resolving module", stderr)
                self.assertIn("checking driver", stderr)
                self.assertNotIn("resolving module", stdout)
                self.assertNotIn("checking driver", stdout)
                if status == "exception":
                    self.assertEqual(payload["module_preflight"]["error"], "driver failed")

    def test_module_diagnostics_stay_on_stdout_in_text_mode(self) -> None:
        code, stdout, stderr = self._run_noisy_module("ok", json_mode=False)
        self.assertEqual(code, 0)
        self.assertIn("resolving module", stdout)
        self.assertIn("checking driver", stdout)
        self.assertIn("exit_code=0", stdout)
        self.assertEqual(stderr, "")

    def test_driver_child_stdout_does_not_prefix_json(self) -> None:
        for status in ("ok", "exception"):
            with self.subTest(status=status):
                code, stdout, stderr = self._run_child_stdout(status, json_mode=True)
                payload = json.loads(stdout)
                self.assertEqual(payload["ok"], status == "ok")
                self.assertEqual(payload["code"], code)
                self.assertNotIn("child-stdout-marker", stdout)
                self.assertIn("child-stdout-marker", stderr)
                if status == "exception":
                    self.assertEqual(payload["module_preflight"]["error"], "driver failed")

    def test_driver_child_stdout_stays_on_stdout_in_text_mode(self) -> None:
        code, stdout, stderr = self._run_child_stdout("ok", json_mode=False)
        self.assertEqual(code, 0)
        self.assertIn("child-stdout-marker", stdout)
        self.assertIn("checking driver", stdout)
        self.assertIn("exit_code=0", stdout)
        self.assertNotIn("child-stdout-marker", stderr)

    def _run_child_stdout(self, status: str, *, json_mode: bool) -> tuple[int, str, str]:
        # unittest shares this process. On a pipe, stdout is block-buffered, so
        # earlier output is still sitting there until something flushes it.
        sys.stdout.flush()
        sys.stderr.flush()
        out_read, out_write = os.pipe()
        err_read, err_write = os.pipe()
        saved_out = os.dup(1)
        saved_err = os.dup(2)
        try:
            os.dup2(out_write, 1)
            os.dup2(err_write, 2)
            os.close(out_write)
            os.close(err_write)
            out_write = err_write = -1
            code = self._invoke_child_driver(status, json_mode=json_mode)
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
            os.close(saved_out)
            os.close(saved_err)
            if out_write >= 0:
                os.close(out_write)
            if err_write >= 0:
                os.close(err_write)
        stdout = os.read(out_read, 1_000_000).decode()
        stderr = os.read(err_read, 1_000_000).decode()
        os.close(out_read)
        os.close(err_read)
        return code, stdout, stderr

    def _invoke_child_driver(self, status: str, *, json_mode: bool) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            resolved = SimpleNamespace(
                execution={"driver": "test/driver"},
                module_dir=Path(tmp),
                inputs={},
                required_credentials=[],
                outputs_publish=[],
            )

            def resolve(**kwargs):
                return resolved

            def driver(request):
                subprocess.run(
                    [sys.executable, "-c", "print('child-stdout-marker', flush=True)"],
                    check=False,
                )
                print("checking driver")
                if status == "exception":
                    raise RuntimeError("driver failed")
                return {"status": "ok", "error": ""}

            argv = ["preflight", "--root", tmp, "--module", "test/module"]
            if json_mode:
                argv.append("--json")
            ns = build_parser().parse_args(argv)
            with (
                patch("hyops.preflight.command.resolve_module", side_effect=resolve),
                patch("hyops.preflight.command.REGISTRY.resolve", return_value=driver),
            ):
                return run(ns)

    def _run_noisy_module(self, status: str, *, json_mode: bool) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            resolved = SimpleNamespace(
                execution={"driver": "test/driver"},
                module_dir=Path(tmp),
                inputs={},
                required_credentials=[],
                outputs_publish=[],
            )

            def resolve(**kwargs):
                print("resolving module")
                return resolved

            def driver(request):
                print("checking driver")
                if status == "exception":
                    raise RuntimeError("driver failed")
                return {"status": status, "error": "driver failed" if status == "error" else ""}

            argv = ["preflight", "--root", tmp, "--module", "test/module"]
            if json_mode:
                argv.append("--json")
            ns = build_parser().parse_args(argv)
            with (
                patch("hyops.preflight.command.resolve_module", side_effect=resolve),
                patch("hyops.preflight.command.REGISTRY.resolve", return_value=driver),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = run(ns)
        return code, stdout.getvalue(), stderr.getvalue()

    def _assert_json_document(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertNotIn("run record:", result.stdout, result.stdout)
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, dict)
        self.assertIn("run record:", result.stderr, result.stderr)
        record = result.stderr.split("run record:", 1)[1].strip()
        log = Path(record) / "output.log"
        self.assertTrue(log.is_file(), result.stderr)
        self.assertIn('"results"', log.read_text(encoding="utf-8"))
        return payload


if __name__ == "__main__":
    unittest.main()
