from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

from hyops.validators.platform.linux.containerlab_gui import validate


class ContainerlabGUIValidatorTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        spec = yaml.safe_load(
            (
                root
                / "modules"
                / "platform"
                / "linux"
                / "containerlab-gui"
                / "spec.yml"
            ).read_text(encoding="utf-8")
        )
        self.inputs = dict(spec["inputs"]["defaults"])
        self.inputs["target_host"] = "127.0.0.1"

    def test_default_contract_is_valid(self) -> None:
        validate(self.inputs)

    def test_operator_user_must_be_a_posix_account_name(self) -> None:
        self.inputs["containerlab_gui_operator_user"] = "bad:user"
        with self.assertRaisesRegex(ValueError, "operator_user is invalid"):
            validate(self.inputs)

    def test_root_cannot_be_the_managed_gui_operator(self) -> None:
        self.inputs["containerlab_gui_operator_user"] = "root"
        with self.assertRaisesRegex(ValueError, "operator_user is invalid"):
            validate(self.inputs)

    def test_local_operator_user_can_be_resolved_by_ansible(self) -> None:
        self.inputs["local_execution"] = True
        self.inputs["containerlab_gui_operator_user"] = "{{ ansible_user_id }}"
        with patch(
            "hyops.validators.platform.linux._eve_ng_common.Path.read_text",
            return_value='ID=ubuntu\nVERSION_ID="24.04"\n',
        ):
            validate(self.inputs)

    def test_remote_operator_user_cannot_be_deferred(self) -> None:
        self.inputs["containerlab_gui_operator_user"] = "{{ ansible_user_id }}"
        with self.assertRaisesRegex(ValueError, "operator_user is invalid"):
            validate(self.inputs)

    def test_state_directory_cannot_be_exposed_below_labs_root(self) -> None:
        self.inputs["containerlab_gui_state_dir"] = (
            "/var/lib/hybridops/containerlab/labs/private"
        )
        with self.assertRaisesRegex(ValueError, "must be outside"):
            validate(self.inputs)

    def test_root_directory_is_rejected(self) -> None:
        self.inputs["containerlab_gui_labs_dir"] = "/"
        with self.assertRaisesRegex(ValueError, "absolute non-root"):
            validate(self.inputs)

    def test_container_names_must_differ(self) -> None:
        self.inputs["containerlab_gui_web_name"] = self.inputs[
            "containerlab_gui_api_name"
        ]
        with self.assertRaisesRegex(ValueError, "container names must differ"):
            validate(self.inputs)

    def test_authorization_groups_must_differ(self) -> None:
        self.inputs["containerlab_gui_api_superuser_group"] = self.inputs[
            "containerlab_gui_api_user_group"
        ]
        with self.assertRaisesRegex(ValueError, "groups must differ"):
            validate(self.inputs)

    def test_managed_password_rejects_chpasswd_delimiters(self) -> None:
        self.inputs["containerlab_gui_manage_operator_password"] = True
        self.inputs["containerlab_gui_operator_password"] = "bad:password"
        with self.assertRaisesRegex(ValueError, "unsupported character"):
            validate(self.inputs)

    def test_gui_image_requires_a_non_empty_tag(self) -> None:
        self.inputs["containerlab_gui_web_image"] = "registry.example/gui:"
        with self.assertRaisesRegex(ValueError, "explicit non-latest tag"):
            validate(self.inputs)
