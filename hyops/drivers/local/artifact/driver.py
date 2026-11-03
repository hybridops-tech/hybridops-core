"""Manage a bounded, deterministic artifact in durable runtime state."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.packs import PackResolveError, resolve_pack_stack
from hyops.runtime.refs import normalize_module_ref
from hyops.runtime.state import write_json_atomic


_DRIVER_REF = "local/artifact"
_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
_MANAGED_STATE_ROOT = Path("managed") / "local-artifact"
_MAX_ARTIFACT_BYTES = 64 * 1024
_PROFILE_REF = re.compile(r"^[a-z0-9][a-z0-9.-]*@v[0-9]+(?:\.[0-9]+)*$")
_OUTPUT_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_CAPABILITY = re.compile(r"^cap\.[a-z0-9][a-z0-9._-]{0,95}$")
_DRIFT_MESSAGE = (
    "managed artifact differs from declared intent; reset it through the owning "
    "module lifecycle before retrying"
)


@dataclass(frozen=True)
class LocalArtifactContract:
    relative_path: Path
    module_refs: frozenset[str]
    output_prefix: str
    capability: str


def _result(request: dict[str, Any]) -> dict[str, Any]:
    execution = request.get("execution")
    if not isinstance(execution, dict):
        execution = {}
    return {
        "status": "error",
        "run_id": str(request.get("run_id") or ""),
        "command": str(request.get("command") or ""),
        "driver": {
            "ref": str(execution.get("driver") or ""),
            "profile": str(execution.get("profile") or ""),
            "pack_id": str(execution.get("pack_id") or ""),
        },
        "normalized_outputs": {},
        "warnings": [],
    }


def _fail(ev: EvidenceWriter, result: dict[str, Any], message: str) -> dict[str, Any]:
    result["status"] = "error"
    result["error"] = message
    ev.write_json("driver_result.json", result)
    return result


def _load_yaml(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"failed to load {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a mapping")
    return payload


def _validate_profile(profile_ref: str) -> None:
    if not _PROFILE_REF.fullmatch(profile_ref):
        raise ValueError(f"invalid local artifact profile reference: {profile_ref}")
    profile_path = (_PROFILES_DIR / f"{profile_ref}.profile.yml").resolve()
    try:
        profile_path.relative_to(_PROFILES_DIR)
    except ValueError as exc:
        raise ValueError("local artifact profile escaped the profiles directory") from exc
    if not profile_path.is_file():
        raise ValueError(f"unsupported local artifact profile: {profile_ref}")

    profile = _load_yaml(profile_path, label="driver profile")
    if profile.get("api_version") != "hybridops/v1":
        raise ValueError("local artifact profile has an unsupported api_version")
    if profile.get("kind") != "DriverProfile":
        raise ValueError("local artifact profile has an invalid kind")
    if profile.get("profile_ref") != profile_ref or profile.get("driver") != _DRIVER_REF:
        raise ValueError("local artifact profile identity does not match the request")

    policy = profile.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("local artifact profile is missing policy settings")
    if policy.get("credentials") != []:
        raise ValueError("local artifact profile must not require credentials")
    if policy.get("external_tools") != []:
        raise ValueError("local artifact profile must not require external tools")
    if policy.get("network_access") is not False:
        raise ValueError("local artifact profile must disable network access")


def _safe_relative_path(raw: object) -> Path:
    value = str(raw or "").strip()
    posix_path = PurePosixPath(value)
    if (
        not value
        or len(value) > 240
        or posix_path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise ValueError("local artifact path must be a safe relative path")
    return Path(*posix_path.parts)


def _load_contract(pack_id: str, module_ref: str) -> LocalArtifactContract:
    try:
        resolved = resolve_pack_stack(
            driver_ref=_DRIVER_REF,
            pack_id=pack_id,
            require_stack_files=("contract.yml",),
        )
    except PackResolveError as exc:
        raise ValueError(str(exc)) from exc
    contract = _load_yaml(resolved.stack_dir / "contract.yml", label="pack contract")
    if contract.get("api_version") != "hybridops/v1":
        raise ValueError("local artifact pack has an unsupported api_version")
    if contract.get("kind") != "LocalArtifactContract":
        raise ValueError("local artifact pack has an invalid kind")

    artifact = contract.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("local artifact pack is missing artifact settings")
    unknown = sorted(
        str(key)
        for key in artifact
        if str(key) not in {"relative_path", "module_refs", "output_prefix", "capability"}
    )
    if unknown:
        raise ValueError(f"local artifact pack has unknown settings: {', '.join(unknown)}")

    raw_module_refs = artifact.get("module_refs")
    if not isinstance(raw_module_refs, list) or not raw_module_refs:
        raise ValueError("local artifact pack must declare at least one module boundary")
    module_refs: set[str] = set()
    for raw_ref in raw_module_refs:
        value = str(raw_ref or "").strip()
        normalized = normalize_module_ref(value)
        if not normalized or normalized != value:
            raise ValueError(f"local artifact pack has an invalid module boundary: {value}")
        module_refs.add(normalized)
    if module_ref not in module_refs:
        raise ValueError(f"local artifact pack does not permit module: {module_ref}")

    output_prefix = str(artifact.get("output_prefix") or "").strip()
    if not _OUTPUT_PREFIX.fullmatch(output_prefix):
        raise ValueError("local artifact pack has an invalid output prefix")
    capability = str(artifact.get("capability") or "").strip()
    if not _CAPABILITY.fullmatch(capability):
        raise ValueError("local artifact pack has an invalid capability")

    return LocalArtifactContract(
        relative_path=_safe_relative_path(artifact.get("relative_path")),
        module_refs=frozenset(module_refs),
        output_prefix=output_prefix,
        capability=capability,
    )


def _validate_directory_chain(state_dir: Path, artifact_path: Path) -> None:
    current = state_dir
    for part in artifact_path.parent.relative_to(state_dir).parts:
        if current.is_symlink():
            raise ValueError(f"managed artifact directory must not be a symbolic link: {current}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"managed artifact parent must be a directory: {current}")
        current /= part
    if current.is_symlink():
        raise ValueError(f"managed artifact directory must not be a symbolic link: {current}")
    if current.exists() and not current.is_dir():
        raise ValueError(f"managed artifact parent must be a directory: {current}")


def _runtime_artifact_path(runtime: object, relative_path: Path) -> Path:
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be a mapping")

    root_raw = str(runtime.get("root") or "").strip()
    state_raw = str(runtime.get("state_dir") or "").strip()
    if not root_raw or not state_raw:
        raise ValueError("runtime.root and runtime.state_dir are required")

    root_path = Path(root_raw).expanduser()
    if root_path.is_symlink():
        raise ValueError("runtime.root must not be a symbolic link")
    runtime_root = root_path.resolve()
    state_path = Path(os.path.abspath(str(Path(state_raw).expanduser())))
    if state_path != runtime_root / "state":
        raise ValueError("runtime.state_dir is outside the selected runtime")

    artifact_path = state_path / _MANAGED_STATE_ROOT / relative_path
    _validate_directory_chain(state_path, artifact_path)
    if artifact_path.is_symlink():
        raise ValueError("managed artifact must not be a symbolic link")
    if artifact_path.exists() and not artifact_path.is_file():
        raise ValueError("managed artifact path must be a regular file")
    return artifact_path


def _resolve_artifact(request: dict[str, Any]) -> tuple[LocalArtifactContract, Path]:
    module_ref = normalize_module_ref(str(request.get("module_ref") or ""))
    if not module_ref:
        raise ValueError("module_ref is required")
    execution = request.get("execution")
    if not isinstance(execution, dict):
        raise ValueError("execution must be a mapping")
    if str(execution.get("driver") or "") != _DRIVER_REF:
        raise ValueError("local artifact driver identity does not match the request")

    _validate_profile(str(execution.get("profile") or ""))
    contract = _load_contract(str(execution.get("pack_id") or ""), module_ref)
    artifact_path = _runtime_artifact_path(request.get("runtime"), contract.relative_path)
    return contract, artifact_path


def _desired_payload(module_ref: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": "hybridops/v1",
        "kind": "ManagedLocalArtifact",
        "managed_by": "HybridOps.Core",
        "module_ref": module_ref,
        "operation": {
            "id": str(inputs.get("operation_id") or ""),
            "declared_outcome": str(inputs.get("declared_outcome") or ""),
        },
    }


def _read_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_ARTIFACT_BYTES + 1)
        if len(raw) > _MAX_ARTIFACT_BYTES:
            raise ValueError(
                f"managed artifact exceeds the {_MAX_ARTIFACT_BYTES}-byte size limit"
            )
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(f"managed artifact is not valid bounded JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("managed artifact must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_runtime_artifact(request: dict[str, Any]) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "status": "absent",
        "artifact_path": "",
        "artifact_sha256": "",
        "payload": {},
    }
    try:
        _, artifact_path = _resolve_artifact(request)
        observation["artifact_path"] = str(artifact_path)
        if not artifact_path.exists():
            return observation
        payload = _read_artifact(artifact_path)
        observation.update(
            {
                "status": "present",
                "artifact_sha256": _sha256(artifact_path),
                "payload": payload or {},
            }
        )
    except (OSError, ValueError) as exc:
        observation.update({"status": "unsafe", "error": str(exc)})
    return observation


def _outputs(
    contract: LocalArtifactContract,
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    operation = payload.get("operation")
    if not isinstance(operation, dict):
        operation = {}
    prefix = contract.output_prefix
    return {
        contract.capability: "ready",
        f"{prefix}.artifact_path": str(path),
        f"{prefix}.artifact_sha256": _sha256(path),
        f"{prefix}.declared_outcome": str(operation.get("declared_outcome") or ""),
        f"{prefix}.operation_id": str(operation.get("id") or ""),
        f"{prefix}.verified": True,
    }


def run(request: dict[str, Any]) -> dict[str, Any]:
    evidence_dir = Path(str(request.get("evidence_dir") or "")).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ev = EvidenceWriter(evidence_dir)
    result = _result(request)

    command = str(request.get("command") or "apply").strip().lower()
    if command == "deploy":
        command = "apply"
    result["command"] = command
    if command not in {"apply", "plan", "validate", "destroy", "preflight"}:
        return _fail(ev, result, f"unsupported command for local artifact driver: {command}")

    inputs = request.get("inputs")
    if not isinstance(inputs, dict):
        return _fail(ev, result, "inputs must be a mapping")

    try:
        contract, artifact_path = _resolve_artifact(request)
        module_ref = normalize_module_ref(str(request.get("module_ref") or ""))
        desired = _desired_payload(module_ref, inputs)
    except (OSError, ValueError) as exc:
        return _fail(ev, result, str(exc))

    lifecycle = str(request.get("lifecycle_command") or command).strip().lower()
    removing = command == "destroy" or (command == "preflight" and lifecycle == "destroy")
    try:
        existing = None if removing else _read_artifact(artifact_path)
    except (OSError, ValueError) as exc:
        return _fail(ev, result, str(exc))

    if command == "preflight":
        if lifecycle == "destroy":
            result["status"] = "ok"
            result["normalized_outputs"] = {
                "action": "remove" if artifact_path.exists() else "no-op"
            }
            ev.write_json("driver_result.json", result)
            return result
        if lifecycle in {"apply", "deploy"} and existing is not None and existing != desired:
            return _fail(ev, result, _DRIFT_MESSAGE)
        result["status"] = "ok"
        result["normalized_outputs"] = {
            "action": "no-op" if existing == desired else "create"
        }
        ev.write_json("driver_result.json", result)
        return result

    if command == "validate":
        result["status"] = "ok"
        result["normalized_outputs"] = {"validated": True}
        ev.write_json("driver_result.json", result)
        return result

    if command == "plan":
        action = "no-op" if existing == desired else "create"
        if existing is not None and existing != desired:
            action = "reset-required"
        result["status"] = "ok"
        result["normalized_outputs"] = {"action": action}
        ev.write_json("driver_result.json", result)
        return result

    if command == "destroy":
        existed = artifact_path.exists()
        try:
            if existed:
                artifact_path.unlink()
        except OSError as exc:
            return _fail(ev, result, f"failed to remove managed artifact: {exc}")
        result["status"] = "ok"
        result["normalized_outputs"] = {
            "action": "removed" if existed else "no-op",
            "published_outputs": {contract.capability: "absent"},
        }
        ev.write_json("artifact_observation.json", inspect_runtime_artifact(request))
        ev.write_json("driver_result.json", result)
        return result

    if existing is not None and existing != desired:
        return _fail(ev, result, _DRIFT_MESSAGE)

    try:
        action = "unchanged"
        if existing is None:
            artifact_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(artifact_path.parent, 0o700)
            write_json_atomic(artifact_path, desired, mode=0o600)
            action = "created"
        verified = _read_artifact(artifact_path)
        if verified != desired:
            raise ValueError("managed artifact verification failed after write")
        outputs = _outputs(contract, artifact_path, desired)
    except (OSError, ValueError) as exc:
        return _fail(ev, result, str(exc))

    result["status"] = "ok"
    result["normalized_outputs"] = {
        "action": action,
        "published_outputs": outputs,
    }
    ev.write_json("artifact_observation.json", inspect_runtime_artifact(request))
    ev.write_json("driver_result.json", result)
    return result
