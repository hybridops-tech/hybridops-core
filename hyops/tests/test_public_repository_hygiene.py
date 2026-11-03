"""Checks for workstation-specific paths in public documentation links."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSTATION_LINK = re.compile(
    r"(?:\]\(\s*<?|^\s*\[[^\]]+\]:\s*<?)"
    r"(?:/home/[^/]+/|/Users/[^/]+/|[A-Za-z]:[\\/]Users[\\/][^\\/]+[\\/])"
)


class PublicRepositoryHygieneTests(unittest.TestCase):
    def test_markdown_links_do_not_expose_workstation_paths(self) -> None:
        failures = []
        paths = set(REPO_ROOT.glob("*.md"))
        for root_name in (".github", "blueprints", "hyops", "modules", "pkg"):
            paths.update((REPO_ROOT / root_name).rglob("*.md"))

        for path in sorted(paths):
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if WORKSTATION_LINK.search(line):
                    failures.append(f"{path.relative_to(REPO_ROOT)}:{line_number}")

        self.assertEqual(
            failures,
            [],
            "Markdown links must be repository-relative: " + ", ".join(failures),
        )

    def test_workstation_link_pattern_covers_markdown_link_forms(self) -> None:
        examples = (
            "[guide](/home/alice/project/guide.md)",
            "[guide](</home/alice/my project/guide.md>)",
            "[guide]: /Users/alice/project/guide.md",
            r"[guide](C:\Users\alice\project\guide.md)",
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertRegex(example, WORKSTATION_LINK)


if __name__ == "__main__":
    unittest.main()
