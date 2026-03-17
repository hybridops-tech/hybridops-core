"""Preflight command.

purpose: Validate prerequisites and readiness markers before running init or modules.
Architecture Decision: ADR-N/A (preflight)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from hyops.runtime.exitcodes import OK, CONFIG_INVALID, DEPENDENCY_MISSING, SECRETS_FAILED, INTERNAL_ERROR
from hyops.runtime.evidence import init_evidence_dir, new_run_id
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_resolve import resolve_module
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.readiness import read_marker
from hyops.runtime.module_state import normalize_state_instance
from hyops.runtime.refs import module_id_from_ref, normalize_module_ref
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.source_roots import resolve_input_path, resolve_module_root
from hyops.runtime.vault import VaultAuth, has_password_source, read_env
from hyops.drivers.registry import REGISTRY
from hyops.preflight.checks import CheckResult, which, file_exists


def add_preflight_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("preflight", help="Check local prerequisites and target readiness.")
    p.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    p.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    p.add_argument("--target", default=None, help="Target readiness to check (e.g. proxmox, azure, gcp).")
    p.add_argument("--json", action="store_true", help="Emit JSON output.")
    p.add_argument("--strict", action="store_true", help="Fail if any optional check is not satisfied.")

    p.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    p.add_argument("--vault-password-file", default=None, help="Vault password file.")
    p.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    p.add_argument("--module", default=None, help="Module ref to run driver preflight checks.")
    p.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    p.add_argument("--inputs", default=None, help="Optional module inputs YAML.")
    p.add_argument(
        "--state-instance",
        default=None,
        help="Optional state instance key for module preflight checks (supports multi-instance module usage).",
    )

    p.set_defaults(_handler=run)


def _check_cmd(name: str, cmd: str) -> CheckResult:
    path = which(cmd)
    return CheckResult(name=name, ok=path is not None, detail=path or "missing")


def _check_readiness(meta_dir: Path, target: str) -> CheckResult:
    try:
        m = read_marker(meta_dir, target)
        status = str(m.get("status", "unknown"))
        return CheckResult(name=f"readiness:{target}", ok=(status == "ready"), detail=status)
    except FileNotFoundError:
        return CheckResult(name=f"readiness:{target}", ok=False, detail="missing")
    except Exception as e:
        return CheckResult(name=f"readiness:{target}", ok=False, detail=f"error:{e}")


def _check_vault_access(vault_path: Path, auth: VaultAuth) -> CheckResult:
    if not vault_path.exists():
        return CheckResult(name="vault:file", ok=True, detail="absent")

    if not has_password_source(auth):
        return CheckResult(name="vault:decrypt", ok=False, detail="password source not provided")

    try:
        _ = read_env(vault_path, auth)
        return CheckResult(name="vault:decrypt", ok=True, detail="ok")
    except Exception as e:
        return CheckResult(name="vault:decrypt", ok=False, detail=f"failed:{e}")


def run_module_driver_preflight(
    *,
    paths,
    env_name: str | None,
    module_ref: str,
    module_root: Path,
    inputs_file: Path | None,
    lifecycle_command: str | None = None,
    state_instance: str | None = None,
    assumed_state_ok: set[str] | None = None,
    allow_state_drift_recreate: bool = False,
) -> dict[str, Any]:
    module_ref = normalize_module_ref(str(module_ref or "").strip())
    if not module_ref:
        raise ValueError("module_ref is required")

    ensure_layout(paths)
    resolved = resolve_module(
        module_ref=module_ref,
        module_root=module_root,
        inputs_file=inputs_file,
        state_dir=paths.state_dir,
        runtime_root=paths.root,
        lifecycle_command=lifecycle_command,
        invocation_command="preflight",
        assumed_state_ok=assumed_state_ok,
    )

    driver_ref = str(resolved.execution.get("driver") or "").strip()
    driver_fn = REGISTRY.resolve(driver_ref)

    run_id = new_run_id("preflight")
    module_id = module_id_from_ref(module_ref)
    evidence_root = paths.logs_dir / "module" / (module_id or "unknown_module")
    evidence_dir = init_evidence_dir(evidence_root, run_id)

    request = {
        "command": "preflight",
        "run_id": run_id,
        "module_ref": module_ref,
        "state_instance": str(state_instance or "").strip(),
        "module_dir": str(resolved.module_dir),
        "inputs": resolved.inputs,
        "execution": resolved.execution,
        "requirements": {"credentials": resolved.required_credentials},
        "runtime": {
            "root": str(paths.root),
            "env": str(env_name or ""),
            "logs_dir": str(paths.logs_dir),
            "meta_dir": str(paths.meta_dir),
            "state_dir": str(paths.state_dir),
            "credentials_dir": str(paths.credentials_dir),
            "work_dir": str(paths.work_dir),
            "allow_state_drift_recreate": bool(allow_state_drift_recreate),
        },
        "evidence_dir": str(evidence_dir),
    }
    if lifecycle_command:
        request["lifecycle_command"] = str(lifecycle_command or "").strip().lower()

    drv = driver_fn(request)
    status = str(drv.get("status") or "").strip().lower() or "unknown"
    return {
        "module_ref": module_ref,
        "driver": driver_ref,
        "run_id": run_id,
        "evidence_dir": str(evidence_dir),
        "status": status,
        "error": str(drv.get("error") or ""),
        "required_credentials": list(resolved.required_credentials),
        "outputs_publish": list(resolved.outputs_publish),
    }


def run(ns) -> int:
    try:
        if ns.module or ns.target:
            require_runtime_selection(
                ns.root,
                getattr(ns, "env", None),
                command_label="hyops preflight",
            )
        paths = resolve_runtime_paths(ns.root, getattr(ns, "env", None))
    except Exception as e:
        if ns.json:
            print(_json_dumps({"ok": False, "error": str(e)}))
        else:
            print(f"ERR: failed to resolve runtime paths: {e}")
        return INTERNAL_ERROR

    results: list[CheckResult] = []

    # Common tools used by init workflows.
    for name, cmd in (
        ("cmd:ssh", "ssh"),
        ("cmd:scp", "scp"),
        ("cmd:ansible-vault", "ansible-vault"),
    ):
        results.append(_check_cmd(name, cmd))

    # Runtime layout existence checks.
    results.append(CheckResult(name="runtime:root", ok=file_exists(paths.root), detail=str(paths.root)))
    results.append(CheckResult(name="runtime:meta", ok=file_exists(paths.meta_dir), detail=str(paths.meta_dir)))
    results.append(CheckResult(name="runtime:vault", ok=file_exists(paths.vault_dir), detail=str(paths.vault_dir)))

    vault_path = Path(ns.vault_file).expanduser() if ns.vault_file else (paths.root / "vault" / "bootstrap.vault.env")
    auth = VaultAuth(password_file=ns.vault_password_file, password_command=ns.vault_password_command)
    results.append(_check_vault_access(vault_path, auth))

    if ns.target:
        results.append(_check_readiness(paths.meta_dir, ns.target))

    vault_decrypt_failed = any(r.name == "vault:decrypt" and not r.ok for r in results)
    readiness_failed = any(r.name.startswith("readiness:") and not r.ok for r in results)
    deps_failed = ns.strict and any(r.name.startswith("cmd:") and not r.ok for r in results)

    module_preflight_payload: dict[str, Any] | None = None
    if ns.module:
        module_ref_raw = str(ns.module or "").strip()
        module_ref_for_result = normalize_module_ref(module_ref_raw) or module_ref_raw
        if vault_decrypt_failed:
            detail = "skipped: vault decrypt failed"
            results.append(CheckResult(name=f"module:{module_ref_for_result}", ok=False, detail=detail))
            module_preflight_payload = {
                "module_ref": module_ref_for_result,
                "status": "skipped",
                "error": detail,
            }
        elif readiness_failed:
            detail = "skipped: readiness checks failed"
            results.append(CheckResult(name=f"module:{module_ref_for_result}", ok=False, detail=detail))
            module_preflight_payload = {
                "module_ref": module_ref_for_result,
                "status": "skipped",
                "error": detail,
            }
        elif deps_failed:
            detail = "skipped: missing strict command dependencies"
            results.append(CheckResult(name=f"module:{module_ref_for_result}", ok=False, detail=detail))
            module_preflight_payload = {
                "module_ref": module_ref_for_result,
                "status": "skipped",
                "error": detail,
            }
        else:
            try:
                module_ref = normalize_module_ref(str(ns.module or "").strip())
                if not module_ref:
                    raise ValueError("module_ref is required")

                module_root = resolve_module_root(str(ns.module_root or "modules"))
                inputs_file = resolve_input_path(str(ns.inputs) if ns.inputs else None)
                state_instance = normalize_state_instance(getattr(ns, "state_instance", None))
                module_preflight = run_module_driver_preflight(
                    paths=paths,
                    env_name=getattr(ns, "env", None),
                    module_ref=module_ref,
                    module_root=module_root,
                    inputs_file=inputs_file,
                    lifecycle_command="apply",
                    state_instance=state_instance,
                )
                status = str(module_preflight.get("status") or "").strip().lower()
                detail = str(module_preflight.get("error") or f"status={status}")
                passed = status == "ok"
                results.append(CheckResult(name=f"module:{module_ref}", ok=passed, detail=detail if not passed else "ok"))
                module_preflight_payload = module_preflight
            except Exception as e:
                results.append(CheckResult(name=f"module:{ns.module}", ok=False, detail=f"error:{e}"))
                module_preflight_payload = {
                    "module_ref": str(ns.module or ""),
                    "status": "error",
                    "error": str(e),
                }

    ok = True
    if ns.strict:
        ok = all(r.ok for r in results)
    else:
        # In non-strict mode, only fail on readiness and vault decrypt failures when vault exists.
        for r in results:
            if r.name.startswith("readiness:") and not r.ok:
                ok = False
            if r.name == "vault:decrypt" and vault_path.exists() and not r.ok:
                ok = False
            if r.name.startswith("module:") and not r.ok:
                ok = False

    if ok:
        code = OK
    else:
        # Prioritise readiness/config, then secrets, then deps.
        if any(r.name.startswith("readiness:") and not r.ok for r in results):
            code = CONFIG_INVALID
        elif any(r.name == "vault:decrypt" and not r.ok for r in results):
            code = SECRETS_FAILED
        elif any(r.name.startswith("module:") and not r.ok for r in results):
            code = CONFIG_INVALID
        elif ns.strict and any(r.name.startswith("cmd:") and not r.ok for r in results):
            code = DEPENDENCY_MISSING
        else:
            code = CONFIG_INVALID

    if ns.json:
        payload: dict[str, Any] = {
            "ok": ok,
            "code": code,
            "target": ns.target,
            "runtime_root": str(paths.root),
            "results": [r.__dict__ for r in results],
        }
        if module_preflight_payload is not None:
            payload["module_preflight"] = module_preflight_payload
        print(_json_dumps(payload))
    else:
        for r in results:
            status = "ok" if r.ok else "missing" if r.detail == "missing" else "fail"
            print(f"{status:7} {r.name} {r.detail}")
        print(f"exit_code={code}")

    return int(code)


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, indent=2, sort_keys=True)
