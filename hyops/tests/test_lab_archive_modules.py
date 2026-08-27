from pathlib import Path
from unittest import TestCase

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class LabArchiveModuleTest(TestCase):
    def _published_outputs(self, module: str) -> set[str]:
        path = REPO_ROOT / "modules" / "platform" / "linux" / module / "spec.yml"
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        return set(spec["outputs"]["publish"])

    def test_eve_ng_archive_generation_outputs_are_published(self):
        self.assertTrue(
            {
                "eveng_lab_archive_previous_path",
                "eveng_lab_archive_previous_manifest_path",
                "eveng_lab_archive_previous_node_state_path",
            }.issubset(self._published_outputs("eve-ng-lab-archive"))
        )

    def test_gns3_archive_generation_outputs_are_published(self):
        self.assertTrue(
            {
                "gns3_lab_archive_previous_path",
                "gns3_lab_archive_previous_manifest_path",
            }.issubset(self._published_outputs("gns3-lab-archive"))
        )
