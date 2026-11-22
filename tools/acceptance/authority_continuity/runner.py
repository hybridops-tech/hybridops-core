"""Run the disposable Operation Authority Continuity benchmark."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import yaml

from hyops import __version__
from hyops.runtime.exitcodes import OPERATOR_ERROR

_SCENARIOS = ("stable", "persistent", "reconverged")
_STARTUP_TIMEOUT_S = 300
_NAMESPACE = "hybridops-authority-benchmark"
_CONFIGMAP = "change-authority"
_SERVICE_ACCOUNT = "hybridops-authority-reader"
_RESOURCE_PATH = f"/api/v1/namespaces/{_NAMESPACE}/configmaps/{_CONFIGMAP}"
_CLUSTER_PREFIX_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
_DIGEST_IMAGE_RE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
_PINNED_KIND_IMAGE = (
    "kindest/node@sha256:"
    "452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f"
)
_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
_MANIFEST = f"""\
apiVersion: v1
kind: Namespace
metadata:
  name: {_NAMESPACE}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: {_CONFIGMAP}
  namespace: {_NAMESPACE}
data:
  owner: gitops
  change_ticket: CHG-1001
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {_SERVICE_ACCOUNT}
  namespace: {_NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: authority-reader
  namespace: {_NAMESPACE}
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["{_CONFIGMAP}"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: authority-reader
  namespace: {_NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: authority-reader
subjects:
  - kind: ServiceAccount
    name: {_SERVICE_ACCOUNT}
    namespace: {_NAMESPACE}
"""


class AuthorityContinuityBenchmarkError(RuntimeError):
    """An exercise prerequisite or result failed validation."""


class ClusterCreateError(AuthorityContinuityBenchmarkError):
    """A kind create attempt failed after cleanup was assessed."""

    def __init__(self, message: str, *, cleanup_status: str) -> None:
        super().__init__(message)
        self.cleanup_status = cleanup_status


def _utc_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout_s: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            env=dict(env) if env is not None else None,
            input=input_text,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorityContinuityBenchmarkError(
            f"command failed to run: {command[0]}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if len(detail) > 1000:
            detail = f"{detail[:1000]}..."
        raise AuthorityContinuityBenchmarkError(
            f"command failed (rc={result.returncode}): {' '.join(command)}"
            + (f": {detail}" if detail else "")
        )
    return result


def _run_bytes(
    command: Sequence[str],
    *,
    timeout_s: int,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorityContinuityBenchmarkError(
            f"command failed to run: {command[0]}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-1000:].decode(
            "utf-8",
            errors="replace",
        )
        raise AuthorityContinuityBenchmarkError(
            f"command failed (rc={result.returncode}): {' '.join(command)}"
            + (f": {detail}" if detail else "")
        )
    return result


def _require_tools(names: Sequence[str]) -> None:
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        raise AuthorityContinuityBenchmarkError(
            f"missing required command(s): {', '.join(sorted(missing))}"
        )


def _hyops_executable(core_root: Path) -> str:
    configured = str(os.environ.get("HYOPS_EXECUTABLE") or "").strip()
    candidates = [
        str(core_root / "bin" / "hyops"),
        configured,
        str(sys.argv[0] or "").strip(),
        shutil.which("hyops") or "",
    ]
    for raw in candidates:
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    raise AuthorityContinuityBenchmarkError("unable to resolve the hyops executable")


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _open_private_log(path: Path) -> TextIO:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    return os.fdopen(descriptor, "w", encoding="utf-8")


def _diagnostic_tail(*paths: Path, limit: int = 1500) -> str:
    parts = []
    for path in paths:
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - limit), os.SEEK_SET)
                content = stream.read(limit).decode("utf-8", errors="replace").strip()
        except OSError:
            continue
        if content:
            parts.append(content)
    return "\n".join(parts)[-limit:]


def _kind_clusters() -> set[str]:
    output = _run(["kind", "get", "clusters"], timeout_s=30).stdout
    return {line.strip() for line in output.splitlines() if line.strip()}


def _create_cluster(cluster_name: str, kubeconfig: Path, kind_image: str) -> None:
    if cluster_name in _kind_clusters():
        raise AuthorityContinuityBenchmarkError(
            f"kind cluster already exists: {cluster_name}"
        )
    command = [
        "kind",
        "create",
        "cluster",
        "--name",
        cluster_name,
        "--kubeconfig",
        str(kubeconfig),
        "--wait",
        "180s",
    ]
    if kind_image:
        command.extend(["--image", kind_image])
    try:
        _run(command, timeout_s=600)
    except AuthorityContinuityBenchmarkError as create_error:
        try:
            partial_cluster_exists = cluster_name in _kind_clusters()
        except AuthorityContinuityBenchmarkError:
            partial_cluster_exists = True
        if not partial_cluster_exists:
            raise ClusterCreateError(
                str(create_error),
                cleanup_status="not-created",
            ) from create_error
        try:
            _delete_cluster(cluster_name, kubeconfig)
        except AuthorityContinuityBenchmarkError as cleanup_error:
            raise ClusterCreateError(
                "kind create failed and partial-cluster cleanup failed: "
                f"{cleanup_error}",
                cleanup_status="failed",
            ) from create_error
        raise ClusterCreateError(
            str(create_error),
            cleanup_status="removed",
        ) from create_error


def _delete_cluster(cluster_name: str, kubeconfig: Path) -> None:
    _run(
        [
            "kind",
            "delete",
            "cluster",
            "--name",
            cluster_name,
            "--kubeconfig",
            str(kubeconfig),
        ],
        timeout_s=180,
    )


def _kubectl(kubeconfig: Path, *arguments: str, input_text: str | None = None) -> str:
    return _run(
        ["kubectl", "--kubeconfig", str(kubeconfig), *arguments],
        input_text=input_text,
        timeout_s=180,
    ).stdout


def _cluster_connection(kubeconfig: Path, ca_path: Path) -> tuple[str, str]:
    try:
        payload = yaml.safe_load(kubeconfig.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise AuthorityContinuityBenchmarkError(
            f"failed to read kind kubeconfig: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorityContinuityBenchmarkError(
            "kind kubeconfig must contain a mapping"
        )
    contexts = payload.get("contexts")
    clusters = payload.get("clusters")
    if not isinstance(contexts, list) or not isinstance(clusters, list):
        raise AuthorityContinuityBenchmarkError(
            "kind kubeconfig is missing contexts or clusters"
        )
    current = str(payload.get("current-context") or "")
    context = next(
        (
            item.get("context")
            for item in contexts
            if isinstance(item, dict) and item.get("name") == current
        ),
        None,
    )
    if not isinstance(context, dict):
        raise AuthorityContinuityBenchmarkError(
            "kind kubeconfig current context is invalid"
        )
    cluster_name = str(context.get("cluster") or "")
    cluster = next(
        (
            item.get("cluster")
            for item in clusters
            if isinstance(item, dict) and item.get("name") == cluster_name
        ),
        None,
    )
    if not isinstance(cluster, dict):
        raise AuthorityContinuityBenchmarkError("kind kubeconfig cluster is invalid")
    endpoint = str(cluster.get("server") or "").strip()
    encoded_ca = str(cluster.get("certificate-authority-data") or "").strip()
    if not endpoint.startswith("https://") or not encoded_ca:
        raise AuthorityContinuityBenchmarkError(
            "kind kubeconfig lacks a verified HTTPS endpoint"
        )
    try:
        ca_data = base64.b64decode(encoded_ca, validate=True)
    except ValueError as exc:
        raise AuthorityContinuityBenchmarkError(
            "kind kubeconfig CA data is invalid"
        ) from exc
    ca_path.write_bytes(ca_data)
    ca_path.chmod(0o600)
    return endpoint, str(ca_path)


def _snapshot(kubeconfig: Path, stage: str) -> dict[str, Any]:
    output = _kubectl(
        kubeconfig,
        "get",
        "configmap",
        _CONFIGMAP,
        "--namespace",
        _NAMESPACE,
        "--output",
        "json",
    )
    try:
        payload = json.loads(output)
        metadata = payload["metadata"]
        data = payload.get("data") or {}
        resource_version = str(metadata["resourceVersion"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AuthorityContinuityBenchmarkError(
            "Kubernetes authority snapshot is invalid"
        ) from exc
    if not isinstance(data, dict):
        raise AuthorityContinuityBenchmarkError(
            "Kubernetes authority data must be an object"
        )
    return {
        "stage": stage,
        "resource_version": resource_version,
        "data": {str(key): str(value) for key, value in sorted(data.items())},
    }


def _set_owner(kubeconfig: Path, owner: str) -> None:
    patch = json.dumps({"data": {"owner": owner}}, separators=(",", ":"))
    _kubectl(
        kubeconfig,
        "patch",
        "configmap",
        _CONFIGMAP,
        "--namespace",
        _NAMESPACE,
        "--type",
        "merge",
        "--patch",
        patch,
    )


def _blueprint_payload(
    barrier_dir: Path,
    run_nonce: str,
    timeout_s: int,
) -> dict[str, Any]:
    return {
        "api_version": "hybridops/v1",
        "kind": "BlueprintSpec",
        "blueprint_ref": "acceptance/authority-continuity@v1",
        "mode": "authoritative",
        "metadata": {
            "title": "Authority Continuity Benchmark",
            "description": "Verify authority continuity around one bounded operation.",
            "outcome": "Authority interval evidence records the expected scenario verdict.",
        },
        "policy": {"fail_fast": True, "evidence_required": True},
        "authorities": {
            "change_control": {
                "capability": "resource_authority",
                "provider": "kubernetes",
                "config": {
                    "resource_path": _RESOURCE_PATH,
                    "endpoint_env": "KUBERNETES_API_URL",
                    "token_env": "KUBERNETES_API_TOKEN",
                    "verify_tls": True,
                    "timeout_s": 5,
                    "instance_id": "authority-continuity-benchmark",
                },
            }
        },
        "steps": [
            {
                "id": "observed_operation",
                "module_ref": "acceptance/core/authority-window",
                "action": "deploy",
                "phase": "operations",
                "with_deps": False,
                "skip_if_state_ok": False,
                "contracts": {
                    "requires_authority": {
                        "ref": "change_control",
                        "capability": "resource_authority",
                    },
                    "authority_observation": {
                        "expected_change": "none",
                        "on_unverifiable": "fail",
                    },
                },
                "inputs": {
                    "barrier_dir": str(barrier_dir),
                    "run_nonce": run_nonce,
                    "timeout_s": timeout_s,
                },
            }
        ],
    }


def _wait_for_window(
    process: subprocess.Popen[str],
    marker: Path,
    run_nonce: str,
    timeout_s: int,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if marker.is_file():
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AuthorityContinuityBenchmarkError(
                    f"operation marker is invalid: {exc}"
                ) from exc
            if isinstance(payload, dict) and payload.get("run_nonce") == run_nonce:
                return
            raise AuthorityContinuityBenchmarkError(
                "operation marker nonce does not match the run"
            )
        if process.poll() is not None:
            process.communicate()
            detail = _diagnostic_tail(stderr_path, stdout_path)
            raise AuthorityContinuityBenchmarkError(
                "HybridOps exited before opening the operation window"
                + (f": {detail[-1500:]}" if detail else "")
            )
        time.sleep(0.05)
    raise AuthorityContinuityBenchmarkError(
        "timed out waiting for the operation window"
    )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise AuthorityContinuityBenchmarkError(
                "HybridOps process did not exit after termination"
            ) from exc


def _deploy_record(runtime_root: Path) -> tuple[Path, dict[str, Any]]:
    records = sorted(runtime_root.glob("logs/blueprint/**/deploy.json"))
    if len(records) != 1:
        raise AuthorityContinuityBenchmarkError(
            f"expected one HybridOps deploy record, found {len(records)}"
        )
    try:
        payload = json.loads(records[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityContinuityBenchmarkError(
            f"failed to read HybridOps deploy record: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorityContinuityBenchmarkError(
            "HybridOps deploy record must be an object"
        )
    return records[0], payload


def _validate_result(
    scenario: str,
    returncode: int,
    snapshots: Sequence[Mapping[str, Any]],
    deploy: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "stable": ("stable", "allow", 0),
        "persistent": ("drifted", "deny", OPERATOR_ERROR),
        "reconverged": ("drifted", "deny", OPERATOR_ERROR),
    }[scenario]
    expected_stages = {
        "stable": ("initial", "final"),
        "persistent": ("initial", "mutated", "final"),
        "reconverged": ("initial", "mutated", "restored", "final"),
    }[scenario]
    steps = deploy.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        raise AuthorityContinuityBenchmarkError(
            "HybridOps deploy record has an invalid step result"
        )
    interval = steps[0].get("authority_interval")
    if not isinstance(interval, dict):
        raise AuthorityContinuityBenchmarkError(
            "HybridOps deploy record lacks authority interval evidence"
        )
    if not snapshots:
        raise AuthorityContinuityBenchmarkError(
            "authority scenario did not record any snapshots"
        )
    if any(
        not isinstance(snapshot.get("data"), Mapping)
        or not str(snapshot.get("resource_version") or "")
        for snapshot in snapshots
    ):
        raise AuthorityContinuityBenchmarkError(
            "authority scenario contains an invalid snapshot"
        )
    before = snapshots[0]
    after = snapshots[-1]
    interval_before = interval.get("before")
    interval_after = interval.get("after")
    if not isinstance(interval_before, dict) or not isinstance(interval_after, dict):
        raise AuthorityContinuityBenchmarkError(
            "authority interval observations are invalid"
        )
    final_data_matches = before.get("data") == after.get("data")
    expected_step_status = "ok" if scenario == "stable" else "failed"
    checks = {
        "process_exit_code": returncode == expected[2],
        "module_exit_code": steps[0].get("module_rc") == 0,
        "step_status": steps[0].get("status") == expected_step_status,
        "step_exit_code": steps[0].get("rc") == expected[2],
        "interval_status": interval.get("interval_status") == expected[0],
        "completion_status": interval.get("completion_status") == "fresh",
        "decision": interval.get("decision") == expected[1],
        "before_revision": (
            interval_before.get("token")
            == f"resourceVersion:{before.get('resource_version')}"
        ),
        "after_revision": (
            interval_after.get("token")
            == f"resourceVersion:{after.get('resource_version')}"
        ),
        "stable_revision_continuity": (
            scenario != "stable"
            or before.get("resource_version") == after.get("resource_version")
        ),
        "snapshot_stages": tuple(snapshot.get("stage") for snapshot in snapshots)
        == expected_stages,
        "mutated_owner": all(
            isinstance(snapshot.get("data"), Mapping)
            and snapshot["data"].get("owner") == "manual"
            for snapshot in snapshots
            if snapshot.get("stage") == "mutated"
        ),
        "final_data_comparison": final_data_matches
        == (scenario in {"stable", "reconverged"}),
    }
    return {
        "scenario": scenario,
        "passed": all(checks.values()),
        "checks": checks,
        "process_exit_code": returncode,
        "final_data_matches_initial": final_data_matches,
        "snapshots": list(snapshots),
        "authority_interval": interval,
    }


def _run_scenario(
    *,
    scenario: str,
    kubeconfig: Path,
    work_root: Path,
    output_root: Path,
    core_root: Path,
    env: Mapping[str, str],
    timeout_s: int,
) -> dict[str, Any]:
    _set_owner(kubeconfig, "gitops")
    scenario_root = work_root / "scenarios" / scenario
    runtime_root = scenario_root / "runtime"
    barrier_dir = scenario_root / "barrier"
    blueprint_dir = runtime_root / "config" / "blueprints"
    blueprint_dir.mkdir(parents=True)
    barrier_dir.mkdir(parents=True)
    run_nonce = f"{scenario}-{os.getpid()}"
    blueprint_path = blueprint_dir / "authority-continuity.yml"
    blueprint_path.write_text(
        yaml.safe_dump(
            _blueprint_payload(barrier_dir, run_nonce, timeout_s),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    snapshots = [_snapshot(kubeconfig, "initial")]
    command = [
        _hyops_executable(core_root),
        "--no-color",
        "blueprint",
        "deploy",
        "--file",
        str(blueprint_path),
        "--blueprints-root",
        str(core_root / "blueprints"),
        "--module-root",
        str(_FIXTURE_ROOT / "modules"),
        "--root",
        str(runtime_root),
        "--execute",
        "--yes",
        "--json",
    ]
    stdout_path = scenario_root / "hyops.stdout.log"
    stderr_path = scenario_root / "hyops.stderr.log"
    with (
        _open_private_log(stdout_path) as stdout_stream,
        _open_private_log(stderr_path) as stderr_stream,
    ):
        process = subprocess.Popen(
            command,
            cwd=core_root,
            env=dict(env),
            stdout=stdout_stream,
            stderr=stderr_stream,
            text=True,
            start_new_session=True,
        )
        try:
            _wait_for_window(
                process,
                barrier_dir / "window-open.json",
                run_nonce,
                _STARTUP_TIMEOUT_S,
                stdout_path,
                stderr_path,
            )
            if scenario in {"persistent", "reconverged"}:
                _set_owner(kubeconfig, "manual")
                snapshots.append(_snapshot(kubeconfig, "mutated"))
            if scenario == "reconverged":
                _set_owner(kubeconfig, "gitops")
                snapshots.append(_snapshot(kubeconfig, "restored"))
            snapshots.append(_snapshot(kubeconfig, "final"))
            _write_json_atomic(
                barrier_dir / "window-release.json",
                {"kind": "hybridops/authority-window", "run_nonce": run_nonce},
            )
            try:
                process.communicate(timeout=timeout_s + 120)
            except subprocess.TimeoutExpired as exc:
                _terminate_process(process)
                raise AuthorityContinuityBenchmarkError(
                    "HybridOps did not finish after the operation was released"
                ) from exc
        finally:
            if process.poll() is None:
                _terminate_process(process)

    source_record, deploy = _deploy_record(runtime_root)
    result = _validate_result(
        scenario,
        int(process.returncode),
        snapshots,
        deploy,
    )
    scenario_output = output_root / "scenarios" / scenario
    scenario_output.mkdir(parents=True)
    shutil.copy2(source_record, scenario_output / "deploy.json")
    result["core_run_record"] = f"scenarios/{scenario}/deploy.json"
    _write_json_atomic(scenario_output / "result.json", result)
    return result


def _render_html(report: Mapping[str, Any]) -> str:
    rows = []
    for scenario in report.get("scenarios", []):
        if not isinstance(scenario, Mapping):
            continue
        interval = scenario.get("authority_interval")
        if not isinstance(interval, Mapping):
            interval = {}
        snapshots = scenario.get("snapshots")
        if not isinstance(snapshots, list) or not snapshots:
            snapshots = [{}]
        before = snapshots[0] if isinstance(snapshots[0], Mapping) else {}
        after = snapshots[-1] if isinstance(snapshots[-1], Mapping) else {}
        result_class = "pass" if scenario.get("passed") else "fail"
        result_text = "passed" if scenario.get("passed") else "failed"
        data_equal = "yes" if scenario.get("final_data_matches_initial") else "no"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(scenario.get('scenario') or ''))}</td>"
            f"<td>{html.escape(str(before.get('resource_version') or ''))}</td>"
            f"<td>{html.escape(str(after.get('resource_version') or ''))}</td>"
            f"<td>{data_equal}</td>"
            f"<td>{html.escape(str(interval.get('interval_status') or ''))}</td>"
            f"<td>{html.escape(str(interval.get('decision') or ''))}</td>"
            f'<td class="{result_class}">{result_text}</td>'
            "</tr>"
        )
    result = html.escape(str(report.get("result") or "unknown"))
    generated = html.escape(str(report.get("generated_at") or ""))
    cluster = report.get("cluster")
    cluster = cluster if isinstance(cluster, Mapping) else {}
    version = html.escape(str(cluster.get("kubernetes_version") or ""))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HybridOps Authority Continuity Benchmark</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; color: #17202a; background: #f4f6f7; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 48px 24px; }}
    h1 {{ margin: 0 0 12px; font-size: 32px; letter-spacing: 0; }}
    p {{ margin: 0 0 28px; color: #4d5966; line-height: 1.55; }}
    .summary {{ display: flex; gap: 28px; margin: 24px 0 32px; flex-wrap: wrap; }}
    .summary div {{ border-left: 3px solid #2874a6; padding-left: 12px; }}
    .summary strong {{ display: block; font-size: 13px; color: #5d6d7e; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d5d8dc; }}
    th, td {{ padding: 13px 12px; border-bottom: 1px solid #e5e7e9; text-align: left; }}
    th {{ background: #edf1f3; font-size: 13px; }}
    td {{ font-size: 14px; }}
    .pass {{ color: #1e8449; font-weight: 700; }}
    .fail {{ color: #b03a2e; font-weight: 700; }}
    @media (max-width: 760px) {{
      main {{ padding: 28px 16px; }}
      .table-wrap {{ overflow-x: auto; }}
      th, td {{ white-space: nowrap; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>HybridOps Authority Continuity Benchmark</h1>
    <p>A disposable acceptance benchmark comparing final-state equality with authority continuity across a governed operation.</p>
    <div class="summary">
      <div><strong>Result</strong>{result}</div>
      <div><strong>Kubernetes</strong>{version}</div>
      <div><strong>Generated</strong>{generated}</div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Scenario</th><th>Before RV</th><th>After RV</th><th>Final data equal</th><th>Interval</th><th>Decision</th><th>Check</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""


def _default_output_root() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (
        Path.home()
        / ".hybridops"
        / "acceptance"
        / "authority-continuity"
        / f"{stamp}-{os.getpid()}-{secrets.token_hex(3)}"
    )


def _prepare_output_root(
    raw: str,
    *,
    forbidden_root: Path | None = None,
) -> Path:
    candidate = Path(raw).expanduser() if raw else _default_output_root()
    if candidate.is_symlink():
        raise AuthorityContinuityBenchmarkError(
            "output directory must not be a symbolic link"
        )
    path = candidate.resolve()
    if forbidden_root is not None:
        source_root = forbidden_root.resolve()
        if path == source_root or path.is_relative_to(source_root):
            raise AuthorityContinuityBenchmarkError(
                "output directory must be outside the source checkout"
            )
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise AuthorityContinuityBenchmarkError(
            f"output directory already exists: {path}"
        ) from exc
    return path


def _source_identity(core_root: Path) -> dict[str, Any]:
    git_sha = _run(
        ["git", "-C", str(core_root), "rev-parse", "HEAD"],
        timeout_s=30,
    ).stdout.strip()
    status = _run(
        [
            "git",
            "-C",
            str(core_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        timeout_s=30,
    ).stdout
    listed = _run_bytes(
        [
            "git",
            "-C",
            str(core_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        timeout_s=30,
    ).stdout
    digest = hashlib.sha256()
    paths = sorted(path for path in listed.split(b"\0") if path)
    for raw_path in paths:
        digest.update(len(raw_path).to_bytes(8, "big"))
        digest.update(raw_path)
        path = core_root / os.fsdecode(raw_path)
        if path.is_symlink():
            content = os.fsencode(os.readlink(path))
            kind = b"symlink"
            mode = path.lstat().st_mode & 0o7777
        elif path.is_file():
            content = path.read_bytes()
            kind = b"file"
            mode = path.stat().st_mode & 0o7777
        else:
            content = b""
            kind = b"missing"
            mode = 0
        digest.update(kind)
        digest.update(mode.to_bytes(4, "big"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return {
        "version": __version__,
        "git_sha": git_sha,
        "git_dirty": bool(status.strip()),
        "source_tree_sha256": digest.hexdigest(),
        "source_file_count": len(paths),
    }


def _tool_versions() -> dict[str, str]:
    docker = _run(
        [
            "docker",
            "version",
            "--format",
            "{{.Client.Version}}|{{.Server.Version}}",
        ],
        timeout_s=30,
    ).stdout.strip()
    docker_client, separator, docker_server = docker.partition("|")
    if not separator or not docker_client or not docker_server:
        raise AuthorityContinuityBenchmarkError("Docker version output is invalid")
    kubectl_payload = json.loads(
        _run(
            ["kubectl", "version", "--client", "--output", "json"],
            timeout_s=30,
        ).stdout
    )
    terraform_payload = json.loads(
        _run(["terraform", "version", "-json"], timeout_s=30).stdout
    )
    kubectl_version = str(
        (kubectl_payload.get("clientVersion") or {}).get("gitVersion") or ""
    )
    terraform_version = str(terraform_payload.get("terraform_version") or "")
    kind_version = _run(["kind", "version"], timeout_s=30).stdout.strip()
    terragrunt_version = _run(["terragrunt", "--version"], timeout_s=30).stdout.strip()
    if not all((kubectl_version, terraform_version, kind_version, terragrunt_version)):
        raise AuthorityContinuityBenchmarkError("tool version output is incomplete")
    return {
        "docker_client": docker_client,
        "docker_server": docker_server,
        "kind": kind_version,
        "kubectl": kubectl_version,
        "terraform": terraform_version,
        "terragrunt": terragrunt_version,
    }


def _print_text_report(report: Mapping[str, Any], output_root: Path) -> None:
    print(f"authority continuity benchmark: {report.get('result', 'failed')}")
    print(f"report: {output_root / 'report.html'}")
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return
    for item in scenarios:
        if not isinstance(item, Mapping):
            continue
        interval = item.get("authority_interval")
        if not isinstance(interval, Mapping):
            interval = {}
        print(
            f"  {item.get('scenario', 'unknown')}: "
            f"interval={interval.get('interval_status', 'missing')} "
            f"decision={interval.get('decision', 'missing')} "
            "final_data_equal="
            f"{str(item.get('final_data_matches_initial', False)).lower()}"
        )


def run_benchmark(ns: argparse.Namespace) -> int:
    cluster_prefix = str(ns.cluster_prefix or "hyops-authority").strip()
    if not _CLUSTER_PREFIX_RE.fullmatch(cluster_prefix):
        print(
            "ERR: cluster prefix must be a lowercase DNS-compatible name "
            "of at most 32 characters",
            file=sys.stderr,
        )
        return OPERATOR_ERROR
    cluster_name = f"{cluster_prefix}-{secrets.token_hex(6)}"
    kind_image = str(ns.kind_image or "").strip()
    if not _DIGEST_IMAGE_RE.fullmatch(kind_image):
        print("ERR: kind image must use an explicit sha256 digest", file=sys.stderr)
        return OPERATOR_ERROR
    scenarios = list(dict.fromkeys(ns.scenario or _SCENARIOS))
    cluster_created = False
    output_root: Path | None = None
    execution_error: Exception | None = None
    cleanup_error: Exception | None = None
    cleanup_status = "not-created"
    results: list[dict[str, Any]] = []
    kubernetes_version = "unknown"
    source: dict[str, Any] = {}
    tools: dict[str, str] = {}
    temporary: tempfile.TemporaryDirectory[str] | None = None
    kubeconfig: Path | None = None
    try:
        _require_tools(("docker", "kind", "kubectl", "terraform", "terragrunt"))
        core_root = Path(__file__).resolve().parents[3]
        source = _source_identity(core_root)
        if source["git_dirty"] and not bool(ns.allow_dirty_source):
            raise AuthorityContinuityBenchmarkError(
                "source tree has uncommitted changes; commit them or pass "
                "--allow-dirty-source to record the exact tree hash"
            )
        tools = _tool_versions()
        output_root = _prepare_output_root(
            str(ns.out_dir or ""),
            forbidden_root=core_root,
        )
        temporary = tempfile.TemporaryDirectory(prefix="hyops-authority-continuity-")
        work_root = Path(temporary.name)
        kubeconfig = work_root / "kubeconfig"
        ca_path = work_root / "cluster-ca.crt"
        print(
            f"authority_continuity cluster={cluster_name} status=creating",
            file=sys.stderr,
        )
        _create_cluster(cluster_name, kubeconfig, kind_image)
        cluster_created = True
        cleanup_status = "pending"
        _kubectl(kubeconfig, "apply", "--filename", "-", input_text=_MANIFEST)
        endpoint, ssl_cert_file = _cluster_connection(kubeconfig, ca_path)
        token = _kubectl(
            kubeconfig,
            "create",
            "token",
            _SERVICE_ACCOUNT,
            "--namespace",
            _NAMESPACE,
            "--duration",
            "30m",
        ).strip()
        if not token:
            raise AuthorityContinuityBenchmarkError(
                "Kubernetes did not issue a service-account token"
            )
        version_payload = json.loads(
            _kubectl(kubeconfig, "version", "--output", "json")
        )
        kubernetes_version = str(
            (version_payload.get("serverVersion") or {}).get("gitVersion") or "unknown"
        )

        child_env = os.environ.copy()
        child_env.update(
            {
                "KUBERNETES_API_URL": endpoint,
                "KUBERNETES_API_TOKEN": token,
                "SSL_CERT_FILE": ssl_cert_file,
                "HYOPS_CORE_ROOT": str(core_root),
                "HYOPS_PACKS_ROOT": str(_FIXTURE_ROOT / "packs"),
                "HYOPS_TERRAFORM_BACKEND_MODE": "local",
                "TF_IN_AUTOMATION": "1",
                "NO_COLOR": "1",
            }
        )
        for scenario in scenarios:
            print(
                f"authority_continuity scenario={scenario} status=running",
                file=sys.stderr,
            )
            result = _run_scenario(
                scenario=scenario,
                kubeconfig=kubeconfig,
                work_root=work_root,
                output_root=output_root,
                core_root=core_root,
                env=child_env,
                timeout_s=int(ns.timeout),
            )
            results.append(result)
            status = "passed" if result["passed"] else "failed"
            print(
                f"authority_continuity scenario={scenario} status={status}",
                file=sys.stderr,
            )

        if _source_identity(core_root) != source:
            raise AuthorityContinuityBenchmarkError(
                "source tree changed while the benchmark was running"
            )
        source["verified_after"] = True

    except ClusterCreateError as exc:
        execution_error = exc
        cleanup_status = exc.cleanup_status
    except (
        AuthorityContinuityBenchmarkError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        execution_error = exc
    finally:
        if cluster_created:
            if bool(getattr(ns, "keep_cluster", False)):
                cleanup_status = "retained"
            else:
                try:
                    if kubeconfig is None:
                        raise AuthorityContinuityBenchmarkError(
                            "benchmark kubeconfig is unavailable for cleanup"
                        )
                    _delete_cluster(cluster_name, kubeconfig)
                    cleanup_status = "removed"
                except AuthorityContinuityBenchmarkError as exc:
                    cleanup_status = "failed"
                    cleanup_error = exc
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc

    passed = (
        execution_error is None
        and cleanup_error is None
        and bool(results)
        and all(item["passed"] for item in results)
    )
    report = {
        "api_version": "hybridops/authority-continuity-benchmark/v1",
        "kind": "AuthorityContinuityBenchmarkReport",
        "generated_at": _utc_text(),
        "hybridops_core_version": __version__,
        "source": source,
        "tools": tools,
        "result": "passed" if passed else "failed",
        "cluster": {
            "name": cluster_name,
            "kind_image": kind_image,
            "kubernetes_version": kubernetes_version,
            "authority_scope": _RESOURCE_PATH,
            "authority_access": "get-only",
            "cleanup": cleanup_status,
        },
        "scenarios": results,
    }
    if output_root is not None:
        try:
            _write_json_atomic(output_root / "report.json", report)
            _write_text_atomic(output_root / "report.html", _render_html(report))
        except OSError as exc:
            print(
                f"ERR: authority continuity report write failed: {exc}", file=sys.stderr
            )
            return OPERATOR_ERROR

    if execution_error is not None:
        print(
            f"ERR: authority continuity benchmark failed: {execution_error}",
            file=sys.stderr,
        )
    if cleanup_error is not None:
        print(
            f"ERR: authority continuity benchmark cleanup failed: {cleanup_error}",
            file=sys.stderr,
        )
    if bool(ns.json):
        print(json.dumps(report, indent=2, sort_keys=True))
    elif output_root is not None:
        _print_text_report(report, output_root)
    return 0 if passed else OPERATOR_ERROR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.acceptance.authority_continuity.runner",
        description=(
            "Run the disposable Kubernetes benchmark for Operation Authority "
            "Continuity."
        ),
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=_SCENARIOS,
        help="Run one scenario; repeat to select more than one. Defaults to all.",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Directory for secret-free results.",
    )
    parser.add_argument(
        "--cluster-prefix",
        default="",
        help="Prefix for the generated disposable kind cluster name.",
    )
    parser.add_argument(
        "--kind-image",
        default=_PINNED_KIND_IMAGE,
        help="Digest-pinned kind node image.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        choices=range(10, 301),
        metavar="SECONDS",
        help="Operation-window timeout from 10 to 300 seconds.",
    )
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="Permit an uncommitted source tree and record its exact tree hash.",
    )
    parser.add_argument(
        "--keep-cluster",
        action="store_true",
        help=(
            "Retain the kind cluster; use 'kind export kubeconfig --name NAME' "
            "to inspect it."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the final report as JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return run_benchmark(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
