"""Tests for the pinned workload module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.pinned_workload import validate
from hyops.validators.registry import ModuleValidationError


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "pinned-workload"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(
        {
            "pinned_workload_runtime_files": [
                {"src": "/tmp/runtime.env", "dest": ".runtime/input"}
            ],
            "pinned_workload_evidence_paths": ["reports"],
        }
    )
    return inputs


class PinnedWorkloadValidatorTests(unittest.TestCase):
    def test_separate_runtime_and_evidence_paths_are_valid(self) -> None:
        validate(valid_inputs())

    def test_empty_runtime_files_allow_checkout_root_evidence(self) -> None:
        inputs = valid_inputs()
        inputs["pinned_workload_runtime_files"] = []
        inputs["pinned_workload_evidence_paths"] = ["."]
        validate(inputs)

    def test_destroy_allows_stale_overlapping_paths(self) -> None:
        inputs = valid_inputs()
        inputs["_hyops_lifecycle_command"] = "destroy"
        inputs["pinned_workload_evidence_paths"] = [".runtime"]
        validate(inputs)

    def test_overlapping_runtime_and_evidence_paths_are_rejected(self) -> None:
        cases = (
            (".runtime/input", ".runtime/input"),
            (".runtime/input", ".runtime"),
            (".runtime", ".runtime/output"),
            (".runtime/input", "."),
        )
        for runtime_path, evidence_path in cases:
            with self.subTest(
                runtime_path=runtime_path,
                evidence_path=evidence_path,
            ):
                inputs = valid_inputs()
                inputs["pinned_workload_runtime_files"][0]["dest"] = runtime_path
                inputs["pinned_workload_evidence_paths"] = [evidence_path]
                with self.assertRaisesRegex(
                    ModuleValidationError,
                    "Protected runtime destination.*overlaps retained evidence path",
                ):
                    validate(inputs)

    def test_noncanonical_repository_paths_are_rejected(self) -> None:
        cases = (
            ("pinned_workload_runtime_files", "dest", "../runtime.env"),
            ("pinned_workload_runtime_files", "dest", "runtime//input"),
            ("pinned_workload_runtime_files", "dest", "runtime/./input"),
            ("pinned_workload_evidence_paths", None, "/reports"),
            ("pinned_workload_evidence_paths", None, "reports/../runtime"),
            ("pinned_workload_evidence_paths", None, " reports"),
        )
        for collection, field, value in cases:
            with self.subTest(collection=collection, value=value):
                inputs = valid_inputs()
                if field:
                    inputs[collection][0][field] = value
                else:
                    inputs[collection] = [value]
                with self.assertRaises(ModuleValidationError):
                    validate(inputs)

    def test_runtime_and_evidence_declarations_must_be_lists(self) -> None:
        for field in (
            "pinned_workload_runtime_files",
            "pinned_workload_evidence_paths",
        ):
            with self.subTest(field=field):
                inputs = valid_inputs()
                inputs[field] = "reports"
                with self.assertRaisesRegex(ModuleValidationError, "must be a list"):
                    validate(inputs)


if __name__ == "__main__":
    unittest.main()
