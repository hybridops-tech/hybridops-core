#!/usr/bin/env python3
"""Run the credential-free continuity contract acceptance proof."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

from hyops import __version__
from hyops.authority.models import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityProviderIdentity,
    AuthorityRequirement,
)
from hyops.authority.registry import AuthorityProviderRegistry
from hyops.authority.resolver import AuthorityResolver
from hyops.continuity import (
    AdapterIdentity,
    AdapterRequest,
    AdmissionResult,
    ContinuityContract,
    ContinuityEngine,
    ControllerIdentity,
    EvidenceBinding,
    EvidenceIdentity,
    ExecutionResult,
    InputBinding,
    RecoveryRequest,
    RecoveryResult,
    StageSpec,
    WorkloadIdentity,
)
from hyops.continuity.storage import FileOperationStore


def _write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


class _LocalAuthority:
    name = "local"
    capabilities = frozenset({"continuity"})

    def validate_configuration(self, declaration, context) -> None:
        if declaration.config != {"scope": "acceptance"}:
            raise ValueError("invalid authority scope")

    def evaluate(self, declaration, context) -> AuthorityEvaluation:
        return AuthorityEvaluation(
            healthy=True,
            state="ready",
            result="authority-secret-marker",
            instance="continuity-contract",
            revision="1",
        )


class _LocalAdapter:
    identity = AdapterIdentity(
        name="local",
        distribution="hybridops-core",
        version="acceptance",
        revision="continuity-contract-acceptance",
    )
    operations = frozenset({"prepare", "release", "remove"})

    def __init__(self, root: Path, *, deny_release: bool) -> None:
        self._root = root
        self._deny_release = deny_release
        self.calls: list[tuple[str, str]] = []
        self.prepared_artifact = ""
        self.prepared_digest = ""
        self.release_artifact = ""

    def admit(self, request: AdapterRequest) -> AdmissionResult:
        self.calls.append(("admit", request.stage_id))
        if request.operation == "release" and self._deny_release:
            return AdmissionResult(
                allowed=False,
                reason_code="release_denied",
            )
        return AdmissionResult(allowed=True)

    def execute(self, request: AdapterRequest) -> ExecutionResult:
        self.calls.append(("execute", request.stage_id))
        if request.operation == "prepare":
            artifact = self._root / "recovery-set.json"
            _write_json_new(
                artifact,
                {"source": request.inputs["source"], "verified": True},
            )
            self.prepared_artifact = str(artifact)
            self.prepared_digest = (
                "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            )
            return ExecutionResult(
                outputs={"artifact": str(artifact)},
                evidence=(
                    EvidenceIdentity(
                        name="recovery-set",
                        role="recovery_set",
                        digest=self.prepared_digest,
                    ),
                ),
            )
        self.release_artifact = str(request.inputs["artifact"])
        marker = self._root / "released.json"
        _write_json_new(
            marker,
            {"artifact": request.inputs["artifact"]},
        )
        return ExecutionResult(
            outputs={"release_receipt": str(marker)},
        )

    def recover(self, request: RecoveryRequest) -> RecoveryResult:
        self.calls.append(("recover", request.stage_id))
        Path(request.outputs["artifact"]).unlink(missing_ok=True)
        return RecoveryResult(
            succeeded=True,
        )


def _resolver() -> AuthorityResolver:
    registry = AuthorityProviderRegistry()
    registry.register(
        _LocalAuthority(),
        identity=AuthorityProviderIdentity(
            source="direct",
            distribution="hybridops-core",
            version="acceptance",
            entry_point="continuity_contract.runner:_LocalAuthority",
        ),
    )
    return AuthorityResolver(registry)


def _controller_revision() -> str:
    engine_source = inspect.getsourcefile(ContinuityEngine)
    if engine_source is None:
        raise RuntimeError("continuity engine source identity is unavailable")
    package_root = Path(engine_source).parent
    digest = hashlib.sha256()
    for path in sorted(package_root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _contract(operation_id: str) -> ContinuityContract:
    return ContinuityContract(
        operation_id=operation_id,
        workload=WorkloadIdentity(
            name="acceptance-workload",
            revision="1",
            digest=("sha256:" + hashlib.sha256(b"acceptance-workload:1").hexdigest()),
        ),
        authorities={
            "release-authority": AuthorityDeclaration(
                logical_ref="release-authority",
                capability="continuity",
                provider="local",
                config={"scope": "acceptance"},
            )
        },
        stages=(
            StageSpec(
                id="prepare",
                adapter="local",
                operation="prepare",
                inputs={"source": "acceptance-workload"},
                publish=frozenset({"artifact"}),
                recovery_operation="remove",
            ),
            StageSpec(
                id="release",
                adapter="local",
                operation="release",
                requires=("prepare",),
                input_bindings={
                    "artifact": InputBinding(stage="prepare", output="artifact")
                },
                publish=frozenset({"release_receipt"}),
                evidence_bindings=(
                    EvidenceBinding(
                        stage="prepare",
                        name="recovery-set",
                        role="recovery_set",
                    ),
                ),
                authority=AuthorityRequirement(
                    logical_ref="release-authority",
                    capability="continuity",
                ),
            ),
        ),
    )


def _scenario(root: Path, *, deny_release: bool) -> dict[str, Any]:
    root.mkdir(parents=True)
    adapter = _LocalAdapter(root, deny_release=deny_release)
    store = FileOperationStore(root / "operations")
    engine = ContinuityEngine(
        adapters={"local": adapter},
        authority_gate=_resolver(),
        authority_context=AuthorityContext(
            runtime_root=root,
            state_root=root,
            env={},
        ),
        controller_identity=ControllerIdentity(
            distribution="hybridops-core",
            version=__version__,
            revision=_controller_revision(),
        ),
        operation_store=store,
    )
    expected_status = "recovered" if deny_release else "succeeded"
    expected_closure = "recovered" if deny_release else "completed"
    expected_reason = "adapter_admission_denied" if deny_release else ""
    terminal_path = store.terminal_path(root.name)
    terminal = engine.run(_contract(root.name))
    release_marker = root / "released.json"
    recovery_set = root / "recovery-set.json"
    expected_calls = [
        ("admit", "prepare"),
        ("execute", "prepare"),
        ("admit", "release"),
    ]
    if deny_release:
        expected_calls.append(("recover", "prepare"))
    else:
        expected_calls.append(("execute", "release"))
    release_payload = (
        json.loads(release_marker.read_text(encoding="utf-8"))
        if release_marker.is_file()
        else {}
    )
    terminal_payload = terminal.to_evidence()
    prepared_evidence = terminal.stages[0].evidence
    release_authority = terminal.stages[1].authority_receipt
    terminal_text = terminal_path.read_text(encoding="utf-8")
    checks = {
        "terminal_status": terminal.status == expected_status,
        "terminal_closure": terminal.closure == expected_closure,
        "terminal_reason": terminal.reason_code == expected_reason,
        "terminal_record": terminal_path.is_file(),
        "exact_order": adapter.calls == expected_calls,
        "authority_receipt": (
            release_authority is not None
            and release_authority.provider == "local"
            and release_authority.provider_identity.distribution == "hybridops-core"
        ),
        "content_identity": (
            len(prepared_evidence) == 1
            and prepared_evidence[0].name == "recovery-set"
            and prepared_evidence[0].role == "recovery_set"
            and prepared_evidence[0].digest == adapter.prepared_digest
        ),
        "dependent_output": (
            adapter.release_artifact == adapter.prepared_artifact
            and release_payload.get("artifact") == adapter.prepared_artifact
            if not deny_release
            else not adapter.release_artifact
        ),
        "release_mutation": release_marker.is_file() == (not deny_release),
        "recovery_cleanup": recovery_set.is_file() == (not deny_release),
        "raw_values_absent": all(
            marker not in terminal_text
            for marker in (
                adapter.prepared_artifact,
                "authority-secret-marker",
            )
        ),
        "single_terminal_shape": terminal_payload == json.loads(terminal_text),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "terminal": str(terminal_path),
        "calls": [list(call) for call in adapter.calls],
        "checks": checks,
    }


def run(output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    scenarios = {
        "completed": _scenario(output_root / "completed", deny_release=False),
        "release-denied": _scenario(
            output_root / "release-denied",
            deny_release=True,
        ),
    }
    report = {
        "status": (
            "passed"
            if all(result["status"] == "passed" for result in scenarios.values())
            else "failed"
        ),
        "scenarios": scenarios,
    }
    _write_json_new(output_root / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.output.expanduser().resolve())
    print(f"continuity conformance: {report['status']}")
    print(f"report: {args.output.expanduser().resolve() / 'report.json'}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
