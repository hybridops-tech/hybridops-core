"""Tests for the EVE-NG module validator."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from hyops.blueprint.planner import _required_env_error
from hyops.validators.platform.linux.eve_ng import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "eve-ng"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs["target_host"] = "127.0.0.1"
    return inputs


def user(**overrides: str) -> dict:
    value = {
        "username": "student",
        "name": "Student User",
        "email": "student@example.com",
        "role": "user",
    }
    value.update(overrides)
    return value


class EVENGValidatorTests(unittest.TestCase):
    def test_empty_user_list_remains_valid(self) -> None:
        validate(valid_inputs())

    def test_plaintext_user_password_remains_valid(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_users"] = [user(password="temporary-password")]

        validate(inputs)

    def test_user_password_environment_reference_is_valid(self) -> None:
        inputs = valid_inputs()
        inputs["required_env"].append("EVENG_STUDENT_PASSWORD")
        inputs["eveng_users"] = [user(password_env="EVENG_STUDENT_PASSWORD")]

        validate(inputs)

    def test_missing_user_password_secret_is_reported_by_preflight(self) -> None:
        inputs = valid_inputs()
        inputs["required_env"].append("EVENG_STUDENT_PASSWORD")
        inputs["eveng_users"] = [user(password_env="EVENG_STUDENT_PASSWORD")]
        validate(inputs)

        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "hyops.blueprint.planner.os.environ",
                {
                    "EVENG_ROOT_PASSWORD": "root-password",
                    "EVENG_ADMIN_PASSWORD": "admin-password",
                },
                clear=True,
            ):
                error = _required_env_error(
                    inputs=inputs,
                    action="deploy",
                    env_name="student-lab",
                    runtime_root=Path(tmp_dir),
                )

        self.assertIn("missing required env vars: EVENG_STUDENT_PASSWORD", error)

    def test_user_requires_one_password_source(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_users"] = [user()]

        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate(inputs)

        inputs["eveng_users"] = [
            user(password="temporary-password", password_env="EVENG_STUDENT_PASSWORD")
        ]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate(inputs)

    def test_user_password_environment_reference_must_be_preflighted(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_users"] = [user(password_env="EVENG_STUDENT_PASSWORD")]

        with patch(
            "hyops.validators.platform.linux.eve_ng.validate_target_access"
        ) as target_access:
            with self.assertRaisesRegex(ValueError, "required_env must include"):
                validate(inputs)

        target_access.assert_not_called()

    def test_destroy_does_not_require_user_password_secret(self) -> None:
        inputs = valid_inputs()
        inputs["_hyops_lifecycle_command"] = "destroy"
        inputs["eveng_users"] = [user(password_env="EVENG_STUDENT_PASSWORD")]

        with patch(
            "hyops.validators.platform.linux.eve_ng.validate_target_access",
            return_value={"is_destroy": True},
        ):
            validate(inputs)

    def test_user_password_environment_reference_must_be_a_valid_name(self) -> None:
        inputs = valid_inputs()
        inputs["required_env"].append("not a valid name")
        inputs["eveng_users"] = [user(password_env="not a valid name")]

        with self.assertRaisesRegex(ValueError, "environment variable name"):
            validate(inputs)


if __name__ == "__main__":
    unittest.main()
