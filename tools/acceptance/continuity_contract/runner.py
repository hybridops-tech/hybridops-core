#!/usr/bin/env python3
"""Run the credential-free continuity contract acceptance proof."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import shutil
from dataclasses import replace
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
from hyops.continuity.api import API_KIND, v1alpha1
from hyops.continuity.evidence import RetainedEvidenceReader
from hyops.continuity.storage import FileOperationStore


def _write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _retained_digest(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


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
    operations = frozenset({"prepare", "release", "remove", "clear-scratch"})
    owned_cleanup = frozenset({("prepare", "clear-scratch")})

    def __init__(
        self, root: Path, *, deny_release: bool = False, omit_evidence: bool = False
    ) -> None:
        self._root = root
        self._deny_release = deny_release
        self._omit_evidence = omit_evidence
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
            _write_json_new(self._root / "prepare.tmp", {"stage": request.stage_id})
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
                evidence=()
                if self._omit_evidence
                else (
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
        if request.recovery_operation == "clear-scratch":
            (self._root / "prepare.tmp").unlink()
        elif request.recovery_operation == "remove":
            Path(request.outputs["artifact"]).unlink()
        else:
            raise ValueError("unsupported recovery operation")
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


def _engine(
    root: Path,
    adapter: _LocalAdapter,
    store: FileOperationStore,
    *,
    evidence_reader: RetainedEvidenceReader | None = None,
) -> ContinuityEngine:
    return ContinuityEngine(
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
        evidence_reader=evidence_reader,
    )


def _scenario(root: Path, *, deny_release: bool) -> dict[str, Any]:
    root.mkdir(parents=True)
    adapter = _LocalAdapter(root, deny_release=deny_release)
    store = FileOperationStore(root / "operations")
    engine = _engine(root, adapter, store)
    expected_status = "failed" if deny_release else "succeeded"
    expected_closure = "recovery_failed" if deny_release else "completed"
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
    if not deny_release:
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
            and prepared_evidence[0].digest == _retained_digest(recovery_set)
        ),
        "dependent_output": (
            adapter.release_artifact == adapter.prepared_artifact
            and release_payload.get("artifact") == adapter.prepared_artifact
            if not deny_release
            else not adapter.release_artifact
        ),
        "release_mutation": release_marker.is_file() == (not deny_release),
        "raw_values_absent": all(
            marker not in terminal_text
            for marker in (
                adapter.prepared_artifact,
                "authority-secret-marker",
            )
        ),
        "single_terminal_shape": terminal_payload == json.loads(terminal_text),
    }
    if deny_release:
        checks["cleanup_blocked"] = (
            terminal.stages[0].recovery_status == "blocked"
            and terminal.stages[0].recovery_reason_code == "recovery_effect_unverified"
        )
    return _result(terminal_path, adapter, checks)


def _result(
    terminal_path: Path, adapter: _LocalAdapter, checks: dict[str, bool]
) -> dict[str, Any]:
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "terminal": str(terminal_path),
        "calls": [list(call) for call in adapter.calls],
        "checks": checks,
    }


def _producer_scenario(root: Path, *, omit_evidence: bool) -> dict[str, Any]:
    root.mkdir(parents=True)
    contract = _contract(root.name)
    producer = replace(contract.stages[0], recovery_operation="clear-scratch")
    api_spec = v1alpha1.decode(
        {
            "apiVersion": v1alpha1.API_VERSION_VALUE,
            "kind": API_KIND,
            "metadata": {"name": root.name},
            "spec": {
                "workload": contract.workload.to_evidence(),
                "recoverySets": [
                    {
                        "name": "workload-state",
                        "producer": {
                            "stage": producer.id,
                            "evidence": "recovery-set",
                            "role": "recovery_set",
                        },
                    }
                ],
                "stages": [
                    {
                        "id": producer.id,
                        "operation": producer.operation,
                        "adapterRef": {"name": producer.adapter},
                        "publish": sorted(producer.publish),
                        "recoveryOperation": producer.recovery_operation,
                    }
                ],
            },
        }
    ).spec
    producer = replace(
        producer, produced_evidence=api_spec.producer_evidence_by_stage()[producer.id]
    )
    adapter = _LocalAdapter(root, omit_evidence=omit_evidence)
    store = FileOperationStore(root / "operations")
    _engine(root, adapter, store).run(
        replace(contract, stages=(producer,), authorities={})
    )
    path = store.terminal_path(root.name)
    record = json.loads(path.read_text(encoding="utf-8"))
    (stage,) = record["stages"]
    artifact = root / "recovery-set.json"
    expected_calls = [("admit", producer.id), ("execute", producer.id)]
    if omit_evidence:
        expected_calls.append(("recover", producer.id))
    reason = "missing_producer_evidence" if omit_evidence else ""
    checks = {
        "producer": stage["stage_id"] == producer.id,
        "terminal_status": record.get("status")
        == ("recovered" if omit_evidence else "succeeded"),
        "terminal_closure": record.get("closure")
        == ("recovered" if omit_evidence else "completed"),
        "terminal_reason": record.get("reason_code") == reason,
        "exact_order": adapter.calls == expected_calls,
    }
    if omit_evidence:
        checks.update(
            producer_failure=stage["status"] == "failed"
            and stage.get("reason_code") == reason,
            cleanup=stage["recovery_status"] == "succeeded"
            and not (root / "prepare.tmp").exists(),
            material_retained=_retained_digest(artifact) == adapter.prepared_digest,
        )
    else:
        checks["producer_success"] = stage["status"] == "succeeded"
        digest = _retained_digest(artifact)
        checks["content_identity"] = digest is not None and stage.get("evidence") == [
            {"name": "recovery-set", "role": "recovery_set", "digest": digest}
        ]
    return _result(path, adapter, checks)


class _RetainedFile:
    def __init__(self, path: Path, contract: ContinuityContract) -> None:
        self.path = path
        self.key = (
            contract.operation_id,
            contract.workload,
            "capture",
            "state",
            "recovery",
        )

    def open_evidence(
        self, operation_id, workload, producer_stage, name, role, *, deadline
    ):
        if (operation_id, workload, producer_stage, name, role) != self.key:
            raise FileNotFoundError
        return self.path.open("rb")


class _ComputeAdapter(_LocalAdapter):
    operations = frozenset({"capture", "retire", "restore"})
    destructive_operations = frozenset({"retire"})
    owned_cleanup = frozenset()

    def __init__(self, root: Path, retained: Path, fault: str) -> None:
        super().__init__(root)
        self.source = root / "source" / "state.bin"
        self.retained = retained
        self.replacement = root / "replacement" / "state.bin"
        self.fault = fault

    def admit(self, request: AdapterRequest) -> AdmissionResult:
        decision = super().admit(request)
        if request.operation == "retire":
            if self.fault == "missing":
                self.retained.unlink()
            elif self.fault == "changed":
                self.retained.write_bytes(b"changed since capture")
        return decision

    def execute(self, request: AdapterRequest) -> ExecutionResult:
        self.calls.append(("execute", request.stage_id))
        if request.operation == "capture":
            self.retained.parent.mkdir()
            shutil.copyfile(self.source, self.retained)
            digest = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
            return ExecutionResult(
                evidence=(EvidenceIdentity("state", "recovery", digest),)
            )
        if request.operation == "retire":
            self.source.unlink()
            self.source.parent.rmdir()
        elif request.operation == "restore":
            self.replacement.parent.mkdir()
            shutil.copyfile(self.retained, self.replacement)
        else:
            raise ValueError("unsupported compute operation")
        return ExecutionResult()


def _retirement_contract(operation_id: str) -> ContinuityContract:
    base = _contract(operation_id)
    authority = base.authorities["release-authority"]
    api = v1alpha1.decode(
        {
            "apiVersion": v1alpha1.API_VERSION_VALUE,
            "kind": API_KIND,
            "metadata": {"name": operation_id},
            "spec": {
                "workload": base.workload.to_evidence(),
                "authorities": [
                    {
                        "name": authority.logical_ref,
                        "capability": authority.capability,
                        "provider": authority.provider,
                    }
                ],
                "recoverySets": [
                    {
                        "name": "saved",
                        "producer": {
                            "stage": "capture",
                            "evidence": "state",
                            "role": "recovery",
                        },
                    }
                ],
                "stages": [
                    {
                        "id": key,
                        "operation": key,
                        "adapterRef": {"name": "local"},
                        **fields,
                    }
                    for key, fields in (
                        ("capture", {}),
                        (
                            "retire",
                            {
                                "requires": ["capture"],
                                "destructive": True,
                                "authorityRef": authority.logical_ref,
                                "recoverySets": ["saved"],
                            },
                        ),
                        ("restore", {"requires": ["retire"]}),
                    )
                ],
            },
        }
    ).spec
    bindings = api.recovery_bindings_by_stage()
    produced = api.producer_evidence_by_stage()
    stages = tuple(
        StageSpec(
            id=s.id,
            adapter=s.adapter,
            operation=s.operation,
            requires=s.requires,
            produced_evidence=produced[s.id],
            destructive=s.destructive,
            evidence_bindings=bindings[s.id],
            authority=AuthorityRequirement(s.authority_ref, authority.capability)
            if s.authority_ref
            else None,
        )
        for s in api.stages
    )
    return replace(base, stages=stages)


def _retirement_scenario(root: Path, fault: str) -> dict[str, Any]:
    retained = root / "retained" / "state.bin"
    adapter = _ComputeAdapter(root, retained, fault)
    adapter.source.parent.mkdir(parents=True)
    original = os.urandom(64)
    adapter.source.write_bytes(original)
    baseline = "sha256:" + hashlib.sha256(original).hexdigest()
    contract = _retirement_contract(root.name)
    store = FileOperationStore(root / "operations")
    reader = _RetainedFile(retained, contract)
    _engine(root, adapter, store, evidence_reader=reader).run(contract)
    path = store.terminal_path(contract.operation_id)
    record = json.loads(path.read_text())
    stages = {s["stage_id"]: s for s in record["stages"]}
    capture = stages.get("capture", {})
    retire = stages.get("retire", {})
    reason = {
        "": "",
        "missing": "retained_evidence_unavailable",
        "changed": "retained_evidence_mismatch",
    }[fault]
    calls = [("admit", "capture"), ("execute", "capture"), ("admit", "retire")]
    if not fault:
        calls.extend(
            [("execute", "retire"), ("admit", "restore"), ("execute", "restore")]
        )
    checks = {
        "terminal_status": record.get("status") == ("failed" if fault else "succeeded"),
        "terminal_reason": record.get("reason_code") == reason,
        "captured_identity": capture.get("evidence")
        == [{"name": "state", "role": "recovery", "digest": baseline}],
        "authority_admitted": retire.get("authority_receipt", {}).get("decision")
        == "admitted",
        "exact_order": calls == adapter.calls,
    }
    if fault:
        checks.update(
            retirement_refused=retire.get("reason_code") == reason
            and retire.get("recovery_status") == "not_required",
            source_intact=_retained_digest(adapter.source) == baseline,
            no_replacement=not adapter.replacement.parent.exists(),
        )
    else:
        checks.update(
            source_removed=not adapter.source.parent.exists(),
            retained_intact=_retained_digest(adapter.retained) == baseline,
            restored_state=_retained_digest(adapter.replacement) == baseline,
        )
    return _result(path, adapter, checks)


def run(output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    scenarios = {
        "completed": _scenario(output_root / "completed", deny_release=False),
        "release-denied": _scenario(
            output_root / "release-denied",
            deny_release=True,
        ),
        "producer-only": _producer_scenario(
            output_root / "producer-only", omit_evidence=False
        ),
        "producer-omitted": _producer_scenario(
            output_root / "producer-omitted", omit_evidence=True
        ),
        "retire-restore": _retirement_scenario(output_root / "retire-restore", ""),
        "retire-missing": _retirement_scenario(
            output_root / "retire-missing", "missing"
        ),
        "retire-changed": _retirement_scenario(
            output_root / "retire-changed", "changed"
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
