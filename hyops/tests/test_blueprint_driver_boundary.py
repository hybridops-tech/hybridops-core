import ast
from pathlib import Path
from unittest import TestCase


class BlueprintDriverBoundaryTest(TestCase):
    def test_blueprint_package_does_not_import_driver_implementations(self):
        package_root = Path(__file__).resolve().parents[1] / "blueprint"
        failures: list[str] = []
        for path in sorted(package_root.rglob("*.py")):
            if "tests" in path.relative_to(package_root).parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = str(node.module or "")
                    if module.startswith("hyops.drivers"):
                        failures.append(f"{path.name}:{node.lineno}: {module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("hyops.drivers"):
                            failures.append(f"{path.name}:{node.lineno}: {alias.name}")

        self.assertEqual(failures, [])
