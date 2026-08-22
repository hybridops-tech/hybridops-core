"""Unit tests for tools/ci/check-module-spec-schema.py.

purpose: Exercise the ModuleSpec schema validator against valid and invalid
         spec.yml fixtures written to a temp directory, without touching
         the real modules/ tree.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

# check-module-spec-schema.py uses a hyphenated filename (to match the
# other tools/ci/check-*.py scripts), so it can't be imported with a plain
# `import` statement. We load it directly from its path instead.
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check-module-spec-schema.py"


def _load_script() -> ModuleType:
    """Import check-module-spec-schema.py as a module object."""
    spec = importlib.util.spec_from_file_location("check_module_spec_schema", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


def _write_spec(tmp_path: Path, module_rel_path: str, content: str) -> Path:
    """Write a spec.yml fixture under <tmp_path>/modules/<module_rel_path>/spec.yml."""
    module_dir = tmp_path / "modules" / module_rel_path
    module_dir.mkdir(parents=True, exist_ok=True)
    spec_path = module_dir / "spec.yml"
    spec_path.write_text(content, encoding="utf-8")
    return spec_path


VALID_SPEC = """\
api_version: hybridops/v1
kind: ModuleSpec
module_ref: "core/example/widget"
requirements:
  credentials: []
inputs:
  defaults: {}
execution:
  driver: "iac/terragrunt"
  profile: "azure@v1.0"
outputs:
  publish:
    - widget_id
"""


class TestValidateSpecSchema:
    def test_valid_spec_has_no_failures(self, script: ModuleType, tmp_path: Path) -> None:
        spec_path = _write_spec(tmp_path, "core/example/widget", VALID_SPEC)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert failures == []

    def test_missing_required_key_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace("outputs:\n  publish:\n    - widget_id\n", "")
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("missing required key 'outputs'" in f for f in failures)

    def test_wrong_api_version_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace("api_version: hybridops/v1", "api_version: hybridops/v2")
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("api_version" in f for f in failures)

    def test_wrong_kind_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace("kind: ModuleSpec", "kind: BlueprintSpec")
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("kind" in f for f in failures)

    def test_module_ref_mismatch_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace(
            'module_ref: "core/example/widget"', 'module_ref: "core/example/other-widget"'
        )
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("does not match its directory path" in f for f in failures)

    def test_empty_module_ref_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace('module_ref: "core/example/widget"', 'module_ref: ""')
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("module_ref must be a non-empty string" in f for f in failures)

    def test_execution_missing_driver_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace('driver: "iac/terragrunt"\n', "")
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("execution.driver must be a non-empty string" in f for f in failures)

    def test_execution_not_a_mapping_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace(
            'execution:\n  driver: "iac/terragrunt"\n  profile: "azure@v1.0"\n',
            "execution: not-a-mapping\n",
        )
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("'execution' must be a mapping" in f for f in failures)

    def test_requirements_credentials_must_be_list(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace("credentials: []", "credentials: azure")
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("requirements.credentials must be a list" in f for f in failures)

    def test_outputs_publish_must_be_list(self, script: ModuleType, tmp_path: Path) -> None:
        content = VALID_SPEC.replace("publish:\n    - widget_id", 'publish: "widget_id"')
        spec_path = _write_spec(tmp_path, "core/example/widget", content)

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert any("outputs.publish must be a list" in f for f in failures)

    def test_unreadable_spec_reports_single_failure(self, script: ModuleType, tmp_path: Path) -> None:
        module_dir = tmp_path / "modules" / "core" / "example" / "widget"
        module_dir.mkdir(parents=True, exist_ok=True)
        spec_path = module_dir / "spec.yml"
        spec_path.write_text("not: [valid, yaml:", encoding="utf-8")

        failures = script.validate_spec_schema(spec_path, tmp_path)

        assert len(failures) == 1
        assert "unreadable" in failures[0] or "not a YAML mapping" in failures[0]


class TestCheckSpecSchema:
    def test_no_spec_files_returns_single_failure(self, script: ModuleType, tmp_path: Path) -> None:
        (tmp_path / "modules").mkdir()

        failures, module_count = script.check_spec_schema(tmp_path)

        assert failures == ["modules: no spec.yml files found"]
        assert module_count == 0

    def test_multiple_specs_are_aggregated(self, script: ModuleType, tmp_path: Path) -> None:
        good = VALID_SPEC.replace(
            'module_ref: "core/example/widget"', 'module_ref: "core/example/widget-a"'
        )
        _write_spec(tmp_path, "core/example/widget-a", good)

        bad = VALID_SPEC.replace("kind: ModuleSpec", "kind: BlueprintSpec").replace(
            'module_ref: "core/example/widget"', 'module_ref: "core/example/widget-b"'
        )
        _write_spec(tmp_path, "core/example/widget-b", bad)

        failures, module_count = script.check_spec_schema(tmp_path)

        assert module_count == 2
        assert len(failures) == 1
        assert "widget-b" in failures[0]


class TestMain:
    def test_main_returns_zero_on_success(
        self,
        script: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_spec(tmp_path, "core/example/widget", VALID_SPEC)
        fake_script_path = tmp_path / "tools" / "ci" / "check-module-spec-schema.py"
        monkeypatch.setattr(script, "__file__", str(fake_script_path))

        exit_code = script.main()

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "module spec schema: ok (1 modules)" in captured.out

    def test_main_returns_one_on_failure(
        self,
        script: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        content = VALID_SPEC.replace("kind: ModuleSpec", "kind: BlueprintSpec")
        _write_spec(tmp_path, "core/example/widget", content)
        fake_script_path = tmp_path / "tools" / "ci" / "check-module-spec-schema.py"
        monkeypatch.setattr(script, "__file__", str(fake_script_path))

        exit_code = script.main()

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "ERR:" in captured.err
