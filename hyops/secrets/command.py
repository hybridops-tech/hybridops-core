"""Secrets command.

purpose: Provide core-native secret sync commands for operator workflows.
Architecture Decision: ADR-N/A (secrets command)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import secrets
import string
from dataclasses import dataclass
from pathlib import Path

from hyops.runtime.exitcodes import CONFIG_INVALID, DEPENDENCY_MISSING, OK, SECRETS_FAILED
from hyops.runtime.hashicorp_vault import fetch_secret_value, read_secret_data, resolve_secret_ref, write_secret_data
from hyops.runtime.kv import read_kv_file
from hyops.runtime.module_state_contracts import resolve_project_contract_from_state
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.module_resolve import resolve_module
from hyops.runtime.readiness import read_marker
from hyops.runtime.source_roots import resolve_input_path, resolve_module_root
from hyops.runtime.vault import VaultAuth, merge_set, read_env


@dataclass(frozen=True)
class SecretMapEntry:
    scope: str
    env_key: str
    secret_name: str


def add_secrets_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("secrets", help="Secrets helper commands.")
    ssp = p.add_subparsers(dest="secrets_cmd", required=True)

    q = ssp.add_parser("akv-sync", help="Sync selected Azure Key Vault secrets into runtime vault.")
    q.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    q.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    q.add_argument("--core-root", default=None, help="Override core root used for default map discovery.")
    q.add_argument("--vault-name", default=None, help="Azure Key Vault name (or set AKV_NAME env var).")
    q.add_argument("--scope", default="all", help="Sync scope from map file (default: all).")
    q.add_argument("--map-file", default=None, help="CSV map file: scope,ENV_KEY,AKV_SECRET_NAME.")
    q.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    q.add_argument("--vault-password-file", default=None, help="Vault password file.")
    q.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    q.add_argument("--dry-run", action="store_true", help="Show keys that would sync; do not write vault.")
    q.set_defaults(_handler=run_akv_sync)

    gs = ssp.add_parser("gsm-sync", help="Sync selected GCP Secret Manager secrets into runtime vault.")
    gs.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    gs.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    gs.add_argument("--core-root", default=None, help="Override core root used for default map discovery.")
    gs.add_argument(
        "--project-id",
        default=None,
        help="Override GCP project id used for Secret Manager reads (default: gcp init config or GCP_PROJECT_ID).",
    )
    gs.add_argument(
        "--project-state-ref",
        default=None,
        help="Optional module state ref that publishes outputs.project_id (for example org/gcp/project-factory).",
    )
    gs.add_argument("--scope", default="all", help="Sync scope from map file (default: all).")
    gs.add_argument("--map-file", default=None, help="CSV map file: scope,ENV_KEY,GSM_SECRET_NAME.")
    gs.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    gs.add_argument("--vault-password-file", default=None, help="Vault password file.")
    gs.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    gs.add_argument("--dry-run", action="store_true", help="Show keys that would sync; do not write vault.")
    gs.set_defaults(_handler=run_gsm_sync)

    gp = ssp.add_parser("gsm-persist", help="Persist selected runtime vault secrets into GCP Secret Manager.")
    gp.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    gp.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    gp.add_argument("--core-root", default=None, help="Override core root used for default map discovery.")
    gp.add_argument(
        "--project-id",
        default=None,
        help="Override GCP project id used for Secret Manager writes (default: project state, gcp init config, or GCP_PROJECT_ID).",
    )
    gp.add_argument(
        "--project-state-ref",
        default=None,
        help="Optional module state ref that publishes outputs.project_id (for example org/gcp/project-factory).",
    )
    gp.add_argument("--scope", default="all", help="Persist scope from map file (default: all).")
    gp.add_argument("--map-file", default=None, help="CSV map file: scope,ENV_KEY,GSM_SECRET_NAME.")
    gp.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    gp.add_argument("--vault-password-file", default=None, help="Vault password file.")
    gp.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    gp.add_argument("--dry-run", action="store_true", help="Show keys that would persist; do not write GCP Secret Manager.")
    gp.set_defaults(_handler=run_gsm_persist)

    hv = ssp.add_parser("vault-sync", help="Sync selected HashiCorp Vault secrets into runtime vault.")
    hv.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    hv.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    hv.add_argument("--core-root", default=None, help="Override core root used for default map discovery.")
    hv.add_argument("--vault-addr", default=None, help="HashiCorp Vault address (or set VAULT_ADDR).")
    hv.add_argument(
        "--vault-token-env",
        default="VAULT_TOKEN",
        help="Environment variable that carries the Vault token (default: VAULT_TOKEN).",
    )
    hv.add_argument("--vault-namespace", default=None, help="Optional Vault namespace (or set VAULT_NAMESPACE).")
    hv.add_argument(
        "--vault-engine",
        default="kv-v2",
        choices=["kv-v1", "kv-v2"],
        help="Secret engine mode used to resolve mapped secret paths (default: kv-v2).",
    )
    hv.add_argument("--scope", default="all", help="Sync scope from map file (default: all).")
    hv.add_argument("--map-file", default=None, help="CSV map file: scope,ENV_KEY,VAULT_SECRET_REF.")
    hv.add_argument("--vault-file", default=None, help="Override runtime vault file path (default: runtime vault path).")
    hv.add_argument("--vault-password-file", default=None, help="Vault password file.")
    hv.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    hv.add_argument("--dry-run", action="store_true", help="Show keys that would sync; do not write vault.")
    hv.set_defaults(_handler=run_vault_sync)

    s = ssp.add_parser("set", help="Set one or more env-style secrets into runtime vault.")
    s.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    s.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    s.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    s.add_argument("--vault-password-file", default=None, help="Vault password file.")
    s.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    s.add_argument(
        "--persist",
        choices=["vault", "gsm"],
        default=None,
        help="Optional external authority to persist the provided secrets into after updating the runtime vault.",
    )
    s.add_argument(
        "--persist-scope",
        default="all",
        help="Secret map scope used when --persist=vault (default: all).",
    )
    s.add_argument(
        "--persist-map-file",
        default=None,
        help="Optional secret map file used when --persist=vault or --persist=gsm.",
    )
    s.add_argument(
        "--persist-project-id",
        default=None,
        help="Optional GCP project id used when --persist=gsm.",
    )
    s.add_argument(
        "--persist-project-state-ref",
        default=None,
        help="Optional module state ref that publishes outputs.project_id when --persist=gsm.",
    )
    s.add_argument(
        "--from-env",
        nargs="+",
        default=[],
        help="Copy keys from the current shell environment into the runtime vault.",
    )
    s.add_argument(
        "--from-file",
        nargs="+",
        default=[],
        help="Copy KEY=PATH pairs from local files into the runtime vault (safe for multiline secrets).",
    )
    s.add_argument(
        "pairs",
        nargs="*",
        help="KEY=VALUE pairs to write to the runtime vault.",
    )
    s.set_defaults(_handler=run_set)

    v = ssp.add_parser("show", help="Decrypt and print runtime vault env values.")
    v.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    v.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    v.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    v.add_argument("--vault-password-file", default=None, help="Vault password file.")
    v.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    v.add_argument("--json", action="store_true", help="Print selected values as JSON.")
    v.add_argument(
        "--quiet-missing",
        action="store_true",
        help="Do not fail when requested keys are missing; print available matches only.",
    )
    v.add_argument(
        "keys",
        nargs="*",
        help="Optional env keys to print. If omitted, prints the whole decrypted vault env bundle.",
    )
    v.set_defaults(_handler=run_show)

    x = ssp.add_parser("exec", help="Run a command with runtime vault env exported.")
    x.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    x.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    x.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    x.add_argument("--vault-password-file", default=None, help="Vault password file.")
    x.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    x.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to run (use -- before the command if it contains flags).",
    )
    x.set_defaults(_handler=run_exec)

    e = ssp.add_parser(
        "ensure",
        help=(
            "Generate missing secret env keys and store them into the runtime vault bundle. "
            "This is intended for bootstrap/labs/CI/DR convenience, not as a steady-state secrets store."
        ),
    )
    e.add_argument("--root", default=None, help="Override runtime root (default: ~/.hybridops).")
    e.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    e.add_argument("--vault-file", default=None, help="Override vault file path (default: runtime vault path).")
    e.add_argument("--vault-password-file", default=None, help="Vault password file.")
    e.add_argument("--vault-password-command", default=None, help="Command to output vault password.")
    e.add_argument(
        "--persist",
        choices=["vault", "gsm"],
        default=None,
        help="Optional external authority to persist generated secrets into after updating the runtime vault.",
    )
    e.add_argument(
        "--persist-scope",
        default="all",
        help="Secret map scope used when --persist=vault (default: all).",
    )
    e.add_argument(
        "--persist-map-file",
        default=None,
        help="Optional secret map file used when --persist=vault or --persist=gsm.",
    )
    e.add_argument(
        "--persist-project-id",
        default=None,
        help="Optional GCP project id used when --persist=gsm.",
    )
    e.add_argument(
        "--persist-project-state-ref",
        default=None,
        help="Optional module state ref that publishes outputs.project_id when --persist=gsm.",
    )
    e.add_argument(
        "--module",
        default=None,
        help="Optional module ref to infer required env keys from resolved module inputs.required_env.",
    )
    e.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    e.add_argument("--inputs", default=None, help="Inputs YAML file (used when --module is set).")
    e.add_argument(
        "--length",
        type=int,
        default=None,
        help="Password length to use for generated secrets (default: key-based heuristic).",
    )
    e.add_argument(
        "--length-map",
        nargs="*",
        default=[],
        help="Per-key override: KEY=LEN (e.g. NETBOX_SECRET_KEY=64).",
    )
    e.add_argument(
        "--force",
        action="store_true",
        help="Rotate secrets: overwrite existing values in the vault.",
    )
    e.add_argument("--dry-run", action="store_true", help="Show what would change; do not write vault.")
    e.add_argument(
        "keys",
        nargs="*",
        help="Env keys to ensure in the vault (e.g. NETBOX_DB_PASSWORD NETBOX_SECRET_KEY).",
    )
    e.set_defaults(_handler=run_ensure)


def _find_core_root(ns_core_root: str | None) -> Path | None:
    if ns_core_root:
        return Path(ns_core_root).expanduser().resolve()

    env_root = os.environ.get("HYOPS_CORE_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    cur = Path.cwd().resolve()
    for _ in range(0, 8):
        if (cur / "tools" / "secrets" / "akv").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent

    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
        if r.returncode == 0:
            root = Path(r.stdout.strip()).resolve()
            if (root / "tools" / "secrets" / "akv").exists():
                return root
    except Exception:
        pass

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "tools" / "secrets" / "akv").exists():
            return parent

    return None


def _default_map_file(ns_core_root: str | None) -> Path | None:
    env_map = os.environ.get("HYOPS_AKV_MAP_FILE", "").strip()
    if env_map:
        return Path(env_map).expanduser().resolve()

    core_root = _find_core_root(ns_core_root)
    if not core_root:
        return None
    return core_root / "tools" / "secrets" / "akv" / "map" / "allowed.csv"


def _default_gsm_map_file(ns_core_root: str | None) -> Path | None:
    env_map = os.environ.get("HYOPS_GSM_MAP_FILE", "").strip()
    if env_map:
        return Path(env_map).expanduser().resolve()

    core_root = _find_core_root(ns_core_root)
    if not core_root:
        return None
    return core_root / "tools" / "secrets" / "gsm" / "map" / "allowed.csv"


def _default_hashicorp_vault_map_file(ns_core_root: str | None) -> Path | None:
    env_map = os.environ.get("HYOPS_HASHICORP_VAULT_MAP_FILE", "").strip()
    if env_map:
        return Path(env_map).expanduser().resolve()

    core_root = _find_core_root(ns_core_root)
    if not core_root:
        return None
    return core_root / "tools" / "secrets" / "hashicorp-vault" / "map" / "allowed.csv"


def resolve_default_hashicorp_vault_map_file(ns_core_root: str | None) -> Path | None:
    return _default_hashicorp_vault_map_file(ns_core_root)


def resolve_default_gsm_map_file(ns_core_root: str | None) -> Path | None:
    return _default_gsm_map_file(ns_core_root)


def _load_map(path: Path) -> list[SecretMapEntry]:
    rows: list[SecretMapEntry] = []
    text = path.read_text(encoding="utf-8")
    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("scope,"):
            continue

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            raise ValueError(f"invalid row {idx}: expected scope,ENV_KEY,AKV_SECRET_NAME")

        scope, env_key, secret_name = parts[0], parts[1], parts[2]
        if not scope or not env_key or not secret_name:
            raise ValueError(f"invalid row {idx}: scope/env_key/secret_name must be non-empty")

        rows.append(SecretMapEntry(scope=scope, env_key=env_key, secret_name=secret_name))

    return rows


def _fetch_secret(vault_name: str, secret_name: str) -> str:
    r = subprocess.run(
        [
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            vault_name,
            "--name",
            secret_name,
            "--query",
            "value",
            "-o",
            "tsv",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip() or f"az exited with code {r.returncode}"
        raise RuntimeError(detail)

    value = (r.stdout or "").strip()
    if not value:
        raise RuntimeError("empty secret value")
    return value


def _fetch_gsm_secret(project_id: str, secret_name: str) -> str:
    r = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            secret_name,
            "--project",
            project_id,
            "--quiet",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip() or f"gcloud exited with code {r.returncode}"
        raise RuntimeError(detail)

    value = (r.stdout or "").strip()
    if not value:
        raise RuntimeError("empty secret value")
    return value


def _ensure_gsm_api_ready(project_id: str) -> None:
    r = subprocess.run(
        [
            "gcloud",
            "services",
            "list",
            "--enabled",
            "--project",
            project_id,
            "--filter",
            "config.name=secretmanager.googleapis.com",
            "--format",
            "value(config.name)",
            "--quiet",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip() or f"gcloud exited with code {r.returncode}"
        raise RuntimeError(detail)
    enabled = str(r.stdout or "").strip()
    if enabled != "secretmanager.googleapis.com":
        raise RuntimeError(
            "Secret Manager API is not enabled on project "
            f"{project_id}. Enable it with "
            f"'gcloud services enable secretmanager.googleapis.com --project {project_id}' "
            "or add 'secretmanager.googleapis.com' to org/gcp/project-factory inputs.activate_apis "
            "and re-apply that module."
        )


def _write_gsm_secret(project_id: str, secret_name: str, value: str) -> None:
    describe = subprocess.run(
        [
            "gcloud",
            "secrets",
            "describe",
            secret_name,
            "--project",
            project_id,
            "--quiet",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if describe.returncode == 0:
        command = [
            "gcloud",
            "secrets",
            "versions",
            "add",
            secret_name,
            "--project",
            project_id,
            "--data-file=-",
            "--quiet",
        ]
    else:
        command = [
            "gcloud",
            "secrets",
            "create",
            secret_name,
            "--project",
            project_id,
            "--replication-policy=automatic",
            "--data-file=-",
            "--quiet",
        ]

    result = subprocess.run(
        command,
        text=True,
        input=value,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"gcloud exited with code {result.returncode}"
        raise RuntimeError(detail)


def _expand_secret_ref(raw_ref: str, *, env_name: str, scope: str) -> str:
    ref = str(raw_ref or "").strip()
    if not ref:
        raise ValueError("empty secret ref")
    return ref.format(env=env_name, scope=scope)


def _resolve_paths(ns):
    try:
        return resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None)), ""
    except Exception as e:
        return None, str(e)


def _read_hashicorp_vault_config(paths) -> dict[str, str]:
    config_path = paths.config_dir / "hashicorp-vault.conf"
    if not config_path.exists():
        return {}
    return {str(k): str(v) for k, v in read_kv_file(config_path).items()}


def run_set(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    if not shutil.which("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        return DEPENDENCY_MISSING

    updates: dict[str, str] = {}

    raw_from_env = list(getattr(ns, "from_env", []) or [])
    for idx, key in enumerate(raw_from_env, start=1):
        k = str(key or "").strip()
        if not k:
            print(f"ERR: --from-env entry #{idx} is empty")
            return CONFIG_INVALID
        v = str(os.environ.get(k) or "").strip()
        if not v:
            print(f"ERR: --from-env {k} is not set (or empty) in the current shell")
            return CONFIG_INVALID
        updates[k] = v

    raw_from_file = list(getattr(ns, "from_file", []) or [])
    for idx, raw in enumerate(raw_from_file, start=1):
        token = str(raw or "").strip()
        if not token:
            print(f"ERR: --from-file entry #{idx} is empty")
            return CONFIG_INVALID
        if "=" not in token:
            print(f"ERR: invalid --from-file entry #{idx}: expected KEY=PATH")
            return CONFIG_INVALID
        k, path_raw = token.split("=", 1)
        k = k.strip()
        path_raw = path_raw.strip()
        if not k:
            print(f"ERR: invalid --from-file entry #{idx}: KEY is empty")
            return CONFIG_INVALID
        if not path_raw:
            print(f"ERR: invalid --from-file entry #{idx}: PATH is empty")
            return CONFIG_INVALID
        path = Path(path_raw).expanduser().resolve()
        if not path.exists():
            print(f"ERR: --from-file {k} path not found: {path}")
            return CONFIG_INVALID
        if not path.is_file():
            print(f"ERR: --from-file {k} path is not a file: {path}")
            return CONFIG_INVALID
        try:
            value = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"ERR: failed to read --from-file {k} from {path}: {exc}")
            return CONFIG_INVALID
        if not str(value).strip():
            print(f"ERR: --from-file {k} is empty in {path}")
            return CONFIG_INVALID
        updates[k] = value

    raw_pairs = list(getattr(ns, "pairs", []) or [])
    for idx, raw in enumerate(raw_pairs, start=1):
        token = str(raw or "").strip()
        if not token:
            continue
        if "=" not in token:
            print(f"ERR: invalid pair #{idx}: expected KEY=VALUE")
            return CONFIG_INVALID
        k, v = token.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            print(f"ERR: invalid pair #{idx}: KEY is empty")
            return CONFIG_INVALID
        if not v:
            print(f"ERR: invalid pair #{idx}: VALUE is empty")
            return CONFIG_INVALID
        updates[k] = v

    if not updates:
        print("ERR: no secrets provided. Use --from-env KEY..., --from-file KEY=PATH..., and/or KEY=VALUE pairs.")
        return CONFIG_INVALID

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )

    try:
        merge_set(vault_path, auth, updates)
    except Exception as e:
        print(f"ERR: failed to update vault file {vault_path}: {e}")
        return SECRETS_FAILED

    persist_backend = str(getattr(ns, "persist", None) or "").strip()
    if persist_backend == "vault":
        rc, message = _persist_updates_to_hashicorp_vault(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            scope=str(getattr(ns, "persist_scope", "all") or "all").strip() or "all",
            updates=updates,
            map_file_override=getattr(ns, "persist_map_file", None),
        )
        if rc != OK:
            print(f"ERR: {message}")
            return rc
        print(message)
    elif persist_backend == "gsm":
        rc, message = _persist_updates_to_gsm(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            scope=str(getattr(ns, "persist_scope", "all") or "all").strip() or "all",
            updates=updates,
            map_file_override=getattr(ns, "persist_map_file", None),
            project_id_override=getattr(ns, "persist_project_id", None),
            project_state_ref_override=getattr(ns, "persist_project_state_ref", None),
        )
        if rc != OK:
            print(f"ERR: {message}")
            return rc
        print(message)

    keys = ", ".join(sorted(updates.keys()))
    print(f"stored {len(updates)} keys into {vault_path}")
    print(f"keys: {keys}")
    return OK


def run_akv_sync(ns) -> int:
    vault_name = str(ns.vault_name or os.environ.get("AKV_NAME") or "").strip()
    if not vault_name:
        print("ERR: --vault-name is required (or set AKV_NAME).")
        return CONFIG_INVALID

    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    map_path = (
        Path(ns.map_file).expanduser().resolve()
        if getattr(ns, "map_file", None)
        else _default_map_file(getattr(ns, "core_root", None))
    )
    if not map_path or not map_path.exists():
        print("ERR: secret map file not found. Use --map-file or set HYOPS_AKV_MAP_FILE.")
        return CONFIG_INVALID

    try:
        rows = _load_map(map_path)
    except Exception as e:
        print(f"ERR: failed to load map file {map_path}: {e}")
        return CONFIG_INVALID

    scope = str(getattr(ns, "scope", "all") or "all").strip()
    if scope != "all":
        rows = [row for row in rows if row.scope == scope]
    if not rows:
        print(f"ERR: no mapped secrets found for scope '{scope}' in {map_path}")
        return CONFIG_INVALID

    env_to_secret: dict[str, str] = {}
    for row in rows:
        existing = env_to_secret.get(row.env_key)
        if existing and existing != row.secret_name:
            print(
                f"ERR: conflicting map for env key {row.env_key}: "
                f"{existing} vs {row.secret_name}"
            )
            return CONFIG_INVALID
        env_to_secret[row.env_key] = row.secret_name

    if bool(getattr(ns, "dry_run", False)):
        print(f"dry-run: vault_name={vault_name} scope={scope} map={map_path}")
        for env_key in sorted(env_to_secret.keys()):
            print(f"would-sync {env_key} <= {env_to_secret[env_key]}")
        print(f"count={len(env_to_secret)}")
        return OK

    if not shutil.which("az"):
        print("ERR: missing command: az")
        return DEPENDENCY_MISSING

    if not shutil.which("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        return DEPENDENCY_MISSING

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )

    updates: dict[str, str] = {}
    for env_key in sorted(env_to_secret.keys()):
        secret_name = env_to_secret[env_key]
        try:
            updates[env_key] = _fetch_secret(vault_name, secret_name)
        except Exception as e:
            print(f"ERR: failed to fetch secret '{secret_name}' for key '{env_key}': {e}")
            return SECRETS_FAILED

    try:
        merge_set(vault_path, auth, updates)
    except Exception as e:
        print(f"ERR: failed to update vault file {vault_path}: {e}")
        return SECRETS_FAILED

    print(f"synced {len(updates)} keys into {vault_path}")
    return OK


def _read_gcp_config(paths) -> dict[str, str]:
    config_path = paths.config_dir / "gcp.conf"
    if not config_path.exists():
        return {}
    return {str(k): str(v) for k, v in read_kv_file(config_path).items()}


def resolve_gsm_project_id(
    *,
    paths,
    env_name: str,
    project_id_override: str | None = None,
    project_state_ref_override: str | None = None,
) -> tuple[int, str]:
    project_id = str(project_id_override or "").strip()
    if project_id:
        return OK, project_id

    project_state_ref = str(project_state_ref_override or "").strip()
    if project_state_ref:
        contract_inputs = {"project_state_ref": project_state_ref}
        try:
            resolve_project_contract_from_state(contract_inputs, state_root=paths.state_dir)
        except Exception as exc:
            return CONFIG_INVALID, str(exc)
        project_id = str(contract_inputs.get("project_id") or "").strip()
        if project_id:
            return OK, project_id

    implicit_ref = "org/gcp/project-factory"
    contract_inputs = {"project_state_ref": implicit_ref}
    try:
        resolve_project_contract_from_state(contract_inputs, state_root=paths.state_dir)
    except Exception:
        pass
    else:
        project_id = str(contract_inputs.get("project_id") or "").strip()
        if project_id:
            return OK, project_id

    gcp_cfg = _read_gcp_config(paths)
    project_id = str(
        os.environ.get("GCP_PROJECT_ID")
        or gcp_cfg.get("GCP_PROJECT_ID")
        or ""
    ).strip()
    if project_id:
        return OK, project_id

    return CONFIG_INVALID, (
        "GCP project id is not configured. Provide --project-id, set GCP_PROJECT_ID, "
        "run 'hyops init gcp --env <env>', or apply/use project state "
        "via --project-state-ref (for example org/gcp/project-factory)."
    )


def sync_gsm_to_runtime(
    *,
    paths,
    env_name: str,
    scope: str,
    map_path: Path,
    auth: VaultAuth,
    project_id: str,
    dry_run: bool = False,
    vault_file: Path | None = None,
) -> tuple[int, str]:
    target_vault_path = vault_file or (paths.vault_dir / "bootstrap.vault.env")

    try:
        rows = _load_map(map_path)
    except Exception as exc:
        return CONFIG_INVALID, f"failed to load map file {map_path}: {exc}"

    if scope != "all":
        rows = [row for row in rows if row.scope == scope]
    if not rows:
        return CONFIG_INVALID, f"no mapped secrets found for scope '{scope}' in {map_path}"

    env_to_secret: dict[str, tuple[str, str]] = {}
    for row in rows:
        existing = env_to_secret.get(row.env_key)
        if existing and existing[0] != row.secret_name:
            return CONFIG_INVALID, (
                f"conflicting map for env key {row.env_key}: {existing[0]} vs {row.secret_name}"
            )
        env_to_secret[row.env_key] = (row.secret_name, row.scope)

    if dry_run:
        lines = [
            f"dry-run: project_id={project_id} scope={scope} map={map_path}",
        ]
        for env_key in sorted(env_to_secret.keys()):
            secret_name, row_scope = env_to_secret[env_key]
            expanded = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
            lines.append(f"would-sync {env_key} <= {expanded}")
        lines.append(f"count={len(env_to_secret)}")
        return OK, "\n".join(lines)

    if not shutil.which("gcloud"):
        return DEPENDENCY_MISSING, "missing command: gcloud"

    if not shutil.which("ansible-vault"):
        return DEPENDENCY_MISSING, "missing command: ansible-vault"

    updates: dict[str, str] = {}
    try:
        _ensure_gsm_api_ready(project_id)
    except Exception as exc:
        return CONFIG_INVALID, str(exc)
    for env_key in sorted(env_to_secret.keys()):
        secret_name, row_scope = env_to_secret[env_key]
        secret_name = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
        try:
            updates[env_key] = _fetch_gsm_secret(project_id, secret_name)
        except Exception as exc:
            return SECRETS_FAILED, (
                f"failed to fetch GCP Secret Manager secret '{secret_name}' for key '{env_key}': {exc}"
            )

    try:
        merge_set(target_vault_path, auth, updates)
    except Exception as exc:
        return SECRETS_FAILED, f"failed to update vault file {target_vault_path}: {exc}"

    return OK, f"synced {len(updates)} keys into {target_vault_path}"


def run_gsm_sync(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID

    rc, project_or_message = resolve_gsm_project_id(
        paths=paths,
        env_name=str(getattr(ns, "env", None) or ""),
        project_id_override=getattr(ns, "project_id", None),
        project_state_ref_override=getattr(ns, "project_state_ref", None),
    )
    if rc != OK:
        print(f"ERR: {project_or_message}")
        return rc
    project_id = project_or_message

    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    map_path = (
        Path(ns.map_file).expanduser().resolve()
        if getattr(ns, "map_file", None)
        else _default_gsm_map_file(getattr(ns, "core_root", None))
    )
    if not map_path or not map_path.exists():
        print("ERR: GCP Secret Manager map file not found. Use --map-file or set HYOPS_GSM_MAP_FILE.")
        return CONFIG_INVALID

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    rc, message = sync_gsm_to_runtime(
        paths=paths,
        env_name=str(getattr(ns, "env", None) or ""),
        scope=str(getattr(ns, "scope", "all") or "all").strip() or "all",
        map_path=map_path,
        auth=auth,
        project_id=project_id,
        dry_run=bool(getattr(ns, "dry_run", False)),
        vault_file=vault_path,
    )
    if rc != OK:
        print(f"ERR: {message}")
        return rc
    print(message)
    return OK


def _persist_updates_to_gsm(
    *,
    paths,
    env_name: str,
    scope: str,
    updates: dict[str, str],
    map_file_override: str | None = None,
    project_id_override: str | None = None,
    project_state_ref_override: str | None = None,
    dry_run: bool = False,
) -> tuple[int, str]:
    if not updates:
        return OK, "no updates to persist"

    rc, project_or_message = resolve_gsm_project_id(
        paths=paths,
        env_name=env_name,
        project_id_override=project_id_override,
        project_state_ref_override=project_state_ref_override,
    )
    if rc != OK:
        return rc, project_or_message
    project_id = project_or_message

    map_path = (
        Path(map_file_override).expanduser().resolve()
        if str(map_file_override or "").strip()
        else _default_gsm_map_file(None)
    )
    if not map_path or not map_path.exists():
        return CONFIG_INVALID, "GCP Secret Manager map file is missing"

    try:
        rows = _load_map(map_path)
    except Exception as exc:
        return CONFIG_INVALID, f"failed to load map file {map_path}: {exc}"

    if scope != "all":
        rows = [row for row in rows if row.scope == scope]
    env_to_secret: dict[str, tuple[str, str]] = {}
    for row in rows:
        existing = env_to_secret.get(row.env_key)
        if existing and existing[0] != row.secret_name:
            return CONFIG_INVALID, (
                f"conflicting map for env key {row.env_key}: {existing[0]} vs {row.secret_name}"
            )
        env_to_secret[row.env_key] = (row.secret_name, row.scope)

    missing_mappings = [key for key in updates.keys() if key not in env_to_secret]
    if missing_mappings:
        return CONFIG_INVALID, (
            "no GCP Secret Manager mapping found for keys: " + ", ".join(sorted(missing_mappings))
        )

    if dry_run:
        lines = [f"dry-run: project_id={project_id} scope={scope} map={map_path}"]
        for env_key in sorted(updates.keys()):
            secret_name, row_scope = env_to_secret[env_key]
            expanded = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
            lines.append(f"would-persist {env_key} => {expanded}")
        lines.append(f"count={len(updates)}")
        return OK, "\n".join(lines)

    if not shutil.which("gcloud"):
        return DEPENDENCY_MISSING, "missing command: gcloud"

    try:
        _ensure_gsm_api_ready(project_id)
    except Exception as exc:
        return CONFIG_INVALID, str(exc)

    try:
        for env_key, value in updates.items():
            secret_name, row_scope = env_to_secret[env_key]
            expanded = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
            _write_gsm_secret(project_id, expanded, value)
    except Exception as exc:
        return SECRETS_FAILED, f"failed to persist secrets to GCP Secret Manager: {exc}"

    return OK, f"persisted {len(updates)} keys into GCP Secret Manager"


def run_gsm_persist(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID

    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )
    if not vault_path.exists():
        print(f"ERR: vault file not found: {vault_path}")
        return CONFIG_INVALID

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    try:
        current = read_env(vault_path, auth)
    except Exception as exc:
        print(f"ERR: failed to read vault file {vault_path}: {exc}")
        return SECRETS_FAILED

    map_path = (
        Path(ns.map_file).expanduser().resolve()
        if getattr(ns, "map_file", None)
        else _default_gsm_map_file(getattr(ns, "core_root", None))
    )
    if not map_path or not map_path.exists():
        print("ERR: GCP Secret Manager map file not found. Use --map-file or set HYOPS_GSM_MAP_FILE.")
        return CONFIG_INVALID

    try:
        rows = _load_map(map_path)
    except Exception as exc:
        print(f"ERR: failed to load map file {map_path}: {exc}")
        return CONFIG_INVALID

    scope = str(getattr(ns, "scope", "all") or "all").strip() or "all"
    if scope != "all":
        rows = [row for row in rows if row.scope == scope]
    if not rows:
        print(f"ERR: no mapped secrets found for scope '{scope}' in {map_path}")
        return CONFIG_INVALID

    updates: dict[str, str] = {}
    missing: list[str] = []
    for row in rows:
        value = str(current.get(row.env_key) or "").strip()
        if value:
            updates[row.env_key] = value
        else:
            missing.append(row.env_key)
    if missing:
        print("ERR: runtime vault is missing mapped keys: " + ", ".join(sorted(set(missing))))
        return CONFIG_INVALID

    if bool(getattr(ns, "dry_run", False)):
        rc, message = _persist_updates_to_gsm(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            scope=scope,
            updates=updates,
            map_file_override=getattr(ns, "map_file", None),
            project_id_override=getattr(ns, "project_id", None),
            project_state_ref_override=getattr(ns, "project_state_ref", None),
            dry_run=True,
        )
        if rc != OK:
            print(f"ERR: {message}")
            return rc
        print(message)
        return OK

    rc, message = _persist_updates_to_gsm(
        paths=paths,
        env_name=str(getattr(ns, "env", None) or paths.root.name),
        scope=scope,
        updates=updates,
        map_file_override=getattr(ns, "map_file", None),
        project_id_override=getattr(ns, "project_id", None),
        project_state_ref_override=getattr(ns, "project_state_ref", None),
    )
    if rc != OK:
        print(f"ERR: {message}")
        return rc
    print(message)
    return OK


def sync_hashicorp_vault_to_runtime(
    *,
    paths,
    env_name: str,
    scope: str,
    map_path: Path,
    auth: VaultAuth,
    vault_addr: str,
    token: str,
    namespace: str,
    engine: str,
    dry_run: bool = False,
    vault_file: Path | None = None,
) -> tuple[int, str]:
    target_vault_path = vault_file or (paths.vault_dir / "bootstrap.vault.env")

    try:
        rows = _load_map(map_path)
    except Exception as exc:
        return CONFIG_INVALID, f"failed to load map file {map_path}: {exc}"

    if scope != "all":
        rows = [row for row in rows if row.scope == scope]
    if not rows:
        return CONFIG_INVALID, f"no mapped secrets found for scope '{scope}' in {map_path}"

    env_to_secret: dict[str, tuple[str, str]] = {}
    for row in rows:
        existing = env_to_secret.get(row.env_key)
        if existing and existing[0] != row.secret_name:
            return CONFIG_INVALID, (
                f"conflicting map for env key {row.env_key}: {existing[0]} vs {row.secret_name}"
            )
        env_to_secret[row.env_key] = (row.secret_name, row.scope)

    if dry_run:
        lines = [
            f"dry-run: vault_addr={vault_addr} scope={scope} engine={engine} map={map_path}",
        ]
        for env_key in sorted(env_to_secret.keys()):
            secret_name, row_scope = env_to_secret[env_key]
            expanded = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
            lines.append(f"would-sync {env_key} <= {expanded}")
        lines.append(f"count={len(env_to_secret)}")
        return OK, "\n".join(lines)

    if not shutil.which("ansible-vault"):
        return DEPENDENCY_MISSING, "missing command: ansible-vault"

    updates: dict[str, str] = {}
    for env_key in sorted(env_to_secret.keys()):
        secret_name, row_scope = env_to_secret[env_key]
        secret_ref = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
        try:
            updates[env_key] = fetch_secret_value(
                vault_addr=vault_addr,
                token=token,
                secret_ref=secret_ref,
                env_key=env_key,
                engine=engine,
                namespace=namespace,
            )
        except Exception as exc:
            return SECRETS_FAILED, (
                f"failed to fetch Vault secret '{secret_ref}' for key '{env_key}': {exc}"
            )

    try:
        merge_set(target_vault_path, auth, updates)
    except Exception as exc:
        return SECRETS_FAILED, f"failed to update vault file {target_vault_path}: {exc}"

    return OK, f"synced {len(updates)} keys into {target_vault_path}"


def run_vault_sync(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID

    cfg = _read_hashicorp_vault_config(paths)
    vault_addr = str(
        getattr(ns, "vault_addr", None)
        or os.environ.get("VAULT_ADDR")
        or cfg.get("VAULT_ADDR")
        or ""
    ).strip()
    if not vault_addr:
        print(
            "ERR: Vault address is not configured. Run 'hyops init hashicorp-vault --env <env>' "
            "or pass --vault-addr / set VAULT_ADDR."
        )
        return CONFIG_INVALID

    token_env = str(
        getattr(ns, "vault_token_env", None)
        or cfg.get("VAULT_TOKEN_ENV")
        or "VAULT_TOKEN"
    ).strip() or "VAULT_TOKEN"
    namespace = str(
        getattr(ns, "vault_namespace", None)
        or os.environ.get("VAULT_NAMESPACE")
        or cfg.get("VAULT_NAMESPACE")
        or ""
    ).strip()
    engine = str(
        getattr(ns, "vault_engine", None)
        or cfg.get("VAULT_ENGINE")
        or "kv-v2"
    ).strip().lower() or "kv-v2"

    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    token = str(os.environ.get(token_env) or "").strip()
    if not token and vault_path.exists():
        try:
            token = str(read_env(vault_path, auth).get(token_env) or "").strip()
        except Exception as exc:
            print(f"ERR: failed to read Vault token {token_env} from runtime vault {vault_path}: {exc}")
            return SECRETS_FAILED
    if not token:
        print(
            f"ERR: Vault token is not available. Set {token_env} in shell env, "
            "or run 'hyops init hashicorp-vault --persist-token'."
        )
        return CONFIG_INVALID

    map_path = (
        Path(ns.map_file).expanduser().resolve()
        if getattr(ns, "map_file", None)
        else (
            Path(str(cfg.get("VAULT_MAP_FILE") or "")).expanduser().resolve()
            if str(cfg.get("VAULT_MAP_FILE") or "").strip()
            else _default_hashicorp_vault_map_file(getattr(ns, "core_root", None))
        )
    )
    if not map_path or not map_path.exists():
        print(
            "ERR: Vault secret map file not found. Use --map-file or set HYOPS_HASHICORP_VAULT_MAP_FILE."
        )
        return CONFIG_INVALID

    rc, message = sync_hashicorp_vault_to_runtime(
        paths=paths,
        env_name=str(getattr(ns, "env", None) or ""),
        scope=str(getattr(ns, "scope", "all") or "all").strip() or "all",
        map_path=map_path,
        auth=auth,
        vault_addr=vault_addr,
        token=token,
        namespace=namespace,
        engine=engine,
        dry_run=bool(getattr(ns, "dry_run", False)),
        vault_file=vault_path,
    )
    if rc != OK:
        print(f"ERR: {message}")
        return rc
    print(message)
    return OK


def _resolve_hashicorp_vault_runtime_settings(
    *,
    paths,
    map_file_override: str | None = None,
) -> tuple[str, str, str, str, Path]:
    readiness = read_marker(paths.meta_dir, "hashicorp-vault")
    status = str(readiness.get("status") or "").strip().lower()
    if status != "ready":
        raise ValueError("hashicorp-vault init target is not ready for this env")

    config_path = paths.config_dir / "hashicorp-vault.conf"
    cfg = read_kv_file(config_path)

    vault_addr = str(cfg.get("VAULT_ADDR") or "").strip()
    token_env = str(cfg.get("VAULT_TOKEN_ENV") or "VAULT_TOKEN").strip() or "VAULT_TOKEN"
    namespace = str(cfg.get("VAULT_NAMESPACE") or "").strip()
    engine = str(cfg.get("VAULT_ENGINE") or "kv-v2").strip().lower() or "kv-v2"
    map_path = (
        Path(map_file_override).expanduser().resolve()
        if str(map_file_override or "").strip()
        else (
            Path(str(cfg.get("VAULT_MAP_FILE") or "")).expanduser().resolve()
            if str(cfg.get("VAULT_MAP_FILE") or "").strip()
            else resolve_default_hashicorp_vault_map_file(None)
        )
    )
    if not vault_addr:
        raise ValueError(f"VAULT_ADDR is missing in {config_path}")
    if not map_path or not map_path.exists():
        raise ValueError("HashiCorp Vault secret map file is missing")
    return vault_addr, token_env, namespace, engine, map_path


def _persist_updates_to_hashicorp_vault(
    *,
    paths,
    env_name: str,
    scope: str,
    updates: dict[str, str],
    map_file_override: str | None = None,
) -> tuple[int, str]:
    if not updates:
        return OK, "no updates to persist"

    try:
        vault_addr, token_env, namespace, engine, map_path = _resolve_hashicorp_vault_runtime_settings(
            paths=paths,
            map_file_override=map_file_override,
        )
    except Exception as exc:
        return CONFIG_INVALID, str(exc)

    auth = VaultAuth()
    runtime_vault_file = paths.vault_dir / "bootstrap.vault.env"
    token = str(os.environ.get(token_env) or "").strip()
    if not token and runtime_vault_file.exists():
        try:
            token = str(read_env(runtime_vault_file, auth).get(token_env) or "").strip()
        except Exception as exc:
            return SECRETS_FAILED, (
                f"failed to read runtime vault token {token_env} from {runtime_vault_file}: {exc}"
            )
    if not token:
        return CONFIG_INVALID, (
            f"HashiCorp Vault token not available. Set {token_env} in shell env, or store it in the runtime vault."
        )

    try:
        rows = _load_map(map_path)
    except Exception as exc:
        return CONFIG_INVALID, f"failed to load map file {map_path}: {exc}"

    if scope != "all":
        rows = [row for row in rows if row.scope == scope]
    env_to_secret: dict[str, tuple[str, str]] = {}
    for row in rows:
        existing = env_to_secret.get(row.env_key)
        if existing and existing[0] != row.secret_name:
            return CONFIG_INVALID, (
                f"conflicting map for env key {row.env_key}: {existing[0]} vs {row.secret_name}"
            )
        env_to_secret[row.env_key] = (row.secret_name, row.scope)

    missing_mappings = [key for key in updates.keys() if key not in env_to_secret]
    if missing_mappings:
        return CONFIG_INVALID, (
            "no HashiCorp Vault mapping found for keys: " + ", ".join(sorted(missing_mappings))
        )

    secret_payloads: dict[str, dict[str, object]] = {}
    for env_key, value in updates.items():
        secret_name, row_scope = env_to_secret[env_key]
        secret_ref = _expand_secret_ref(secret_name, env_name=env_name, scope=row_scope)
        _secret_path, field = resolve_secret_ref(secret_ref, engine=engine)
        field_name = field or env_key
        bucket = secret_payloads.setdefault(secret_ref, {})
        bucket[field_name] = value

    try:
        for secret_ref, fields in secret_payloads.items():
            existing = read_secret_data(
                vault_addr=vault_addr,
                token=token,
                secret_ref=secret_ref,
                engine=engine,
                namespace=namespace,
            )
            merged = dict(existing)
            merged.update(fields)
            write_secret_data(
                vault_addr=vault_addr,
                token=token,
                secret_ref=secret_ref,
                data=merged,
                engine=engine,
                namespace=namespace,
            )
    except Exception as exc:
        return SECRETS_FAILED, f"failed to persist secrets to HashiCorp Vault: {exc}"

    return OK, f"persisted {len(updates)} keys into HashiCorp Vault"


def _parse_length_map(raw: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for idx, token in enumerate(raw or [], start=1):
        item = str(token or "").strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"--length-map entry #{idx} must be KEY=LEN")
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise ValueError(f"--length-map entry #{idx} has empty KEY")
        try:
            n = int(v)
        except ValueError as exc:
            raise ValueError(f"--length-map entry #{idx} LEN must be an integer") from exc
        if n < 16:
            raise ValueError(f"--length-map {k} length must be >= 16")
        out[k] = n
    return out


def _default_length_for_key(env_key: str) -> int:
    k = (env_key or "").strip().upper()
    if not k:
        return 32
    # NetBox API tokens are typically 40 characters (DRF Token key max_length=40).
    if k == "NETBOX_API_TOKEN":
        return 40
    if "SECRET_KEY" in k:
        return 64
    if "TOKEN" in k:
        return 48
    if "PASSWORD" in k:
        return 32
    return 32


def _generate_password(length: int) -> str:
    # Use a conservative alphabet that is safe in env files, YAML, shell, and most apps.
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _infer_required_env_from_module(ns, *, state_dir: Path) -> list[str]:
    module_ref = str(getattr(ns, "module", None) or "").strip()
    if not module_ref:
        return []

    module_root = resolve_module_root(str(getattr(ns, "module_root", "modules")))
    inputs_file = resolve_input_path(str(ns.inputs) if getattr(ns, "inputs", None) else None)
    resolved = resolve_module(
        module_ref=module_ref,
        module_root=module_root,
        inputs_file=inputs_file,
        state_dir=state_dir,
    )
    raw = resolved.inputs.get("required_env")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("resolved inputs.required_env must be a list when set")
    out: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        k = str(item or "").strip()
        if not k:
            raise ValueError(f"resolved inputs.required_env[{idx}] is empty")
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def run_ensure(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )

    if not shutil.which("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        return DEPENDENCY_MISSING

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )

    keys: list[str] = []
    # 1) Explicit keys
    for idx, raw in enumerate(list(getattr(ns, "keys", []) or []), start=1):
        k = str(raw or "").strip()
        if not k:
            print(f"ERR: key #{idx} is empty")
            return CONFIG_INVALID
        keys.append(k)

    # 2) Optional module inference
    try:
        inferred = _infer_required_env_from_module(ns, state_dir=paths.state_dir)
        keys += inferred
    except Exception as e:
        print(f"WARN: failed to infer required env from module: {e}")

    # de-dup (preserve order)
    uniq: list[str] = []
    seen: set[str] = set()
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        uniq.append(k)
    keys = uniq

    if not keys:
        print("ERR: no keys provided. Pass env keys and/or use --module to infer inputs.required_env.")
        return CONFIG_INVALID

    try:
        length_map = _parse_length_map(list(getattr(ns, "length_map", []) or []))
    except Exception as e:
        print(f"ERR: {e}")
        return CONFIG_INVALID

    global_length = getattr(ns, "length", None)
    if global_length is not None and int(global_length) < 16:
        print("ERR: --length must be >= 16")
        return CONFIG_INVALID

    force = bool(getattr(ns, "force", False))
    dry_run = bool(getattr(ns, "dry_run", False))

    try:
        existing = read_env(vault_path, auth) if vault_path.exists() else {}
    except Exception as e:
        print(f"ERR: failed to read vault file {vault_path}: {e}")
        return SECRETS_FAILED

    updates: dict[str, str] = {}
    created: list[str] = []
    rotated: list[str] = []
    skipped: list[str] = []

    for k in keys:
        cur = str(existing.get(k) or "").strip()
        if cur and not force:
            skipped.append(k)
            continue

        n = int(length_map.get(k) or (global_length if global_length is not None else _default_length_for_key(k)))
        value = _generate_password(n)
        updates[k] = value
        if cur and force:
            rotated.append(k)
        else:
            created.append(k)

    if dry_run:
        if created:
            print(f"would-create {len(created)} keys into {vault_path}")
            print("keys: " + ", ".join(sorted(created)))
        if rotated:
            print(f"would-rotate {len(rotated)} keys into {vault_path}")
            print("keys: " + ", ".join(sorted(rotated)))
        if skipped:
            print(f"would-skip {len(skipped)} keys (already present)")
        return OK

    if not updates:
        print(f"ok: all requested keys already exist in {vault_path}")
        return OK

    try:
        merge_set(vault_path, auth, updates)
    except Exception as e:
        print(f"ERR: failed to update vault file {vault_path}: {e}")
        return SECRETS_FAILED

    persist_backend = str(getattr(ns, "persist", None) or "").strip()
    if persist_backend == "vault":
        rc, message = _persist_updates_to_hashicorp_vault(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            scope=str(getattr(ns, "persist_scope", "all") or "all").strip() or "all",
            updates=updates,
            map_file_override=getattr(ns, "persist_map_file", None),
        )
        if rc != OK:
            print(f"ERR: {message}")
            return rc
        print(message)
    elif persist_backend == "gsm":
        rc, message = _persist_updates_to_gsm(
            paths=paths,
            env_name=str(getattr(ns, "env", None) or paths.root.name),
            scope=str(getattr(ns, "persist_scope", "all") or "all").strip() or "all",
            updates=updates,
            map_file_override=getattr(ns, "persist_map_file", None),
            project_id_override=getattr(ns, "persist_project_id", None),
            project_state_ref_override=getattr(ns, "persist_project_state_ref", None),
        )
        if rc != OK:
            print(f"ERR: {message}")
            return rc
        print(message)

    if created:
        print(f"created {len(created)} keys into {vault_path}")
    if rotated:
        print(f"rotated {len(rotated)} keys into {vault_path}")
    if skipped:
        print(f"skipped {len(skipped)} keys (already present)")
    print("keys: " + ", ".join(sorted(list(updates.keys()))))
    print("note: values were generated and stored encrypted; they were not printed to stdout.")
    return OK


def run_show(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )
    if not vault_path.exists():
        print(f"ERR: vault file not found: {vault_path}")
        return CONFIG_INVALID

    if not shutil.which("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        return DEPENDENCY_MISSING

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    try:
        env_map = read_env(vault_path, auth)
    except Exception as e:
        print(f"ERR: failed to read vault file {vault_path}: {e}")
        return SECRETS_FAILED

    requested = [str(k or "").strip() for k in list(getattr(ns, "keys", []) or [])]
    requested = [k for k in requested if k]
    missing: list[str] = []
    selected: dict[str, str]
    if requested:
        selected = {}
        for key in requested:
            if key in env_map:
                selected[key] = str(env_map[key])
            else:
                missing.append(key)
        if missing and not bool(getattr(ns, "quiet_missing", False)):
            print("ERR: requested keys not found in vault: " + ", ".join(sorted(missing)))
            return CONFIG_INVALID
    else:
        selected = dict(env_map)

    if bool(getattr(ns, "json", False)):
        print(json.dumps({k: selected[k] for k in sorted(selected.keys())}, indent=2, sort_keys=True))
    else:
        for key in sorted(selected.keys()):
            print(f"{key}={selected[key]}")
    if missing and bool(getattr(ns, "quiet_missing", False)):
        print("WARN: missing keys: " + ", ".join(sorted(missing)))
    return OK


def run_exec(ns) -> int:
    paths, err = _resolve_paths(ns)
    if err:
        print(f"ERR: {err}")
        return CONFIG_INVALID
    vault_path = (
        Path(ns.vault_file).expanduser().resolve()
        if getattr(ns, "vault_file", None)
        else (paths.vault_dir / "bootstrap.vault.env")
    )
    if not vault_path.exists():
        print(f"ERR: vault file not found: {vault_path}")
        return CONFIG_INVALID

    argv = list(getattr(ns, "cmd", []) or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("ERR: no command provided. Usage: hyops secrets exec --env <env> -- <command> [args...]")
        return CONFIG_INVALID

    if not shutil.which("ansible-vault"):
        print("ERR: missing command: ansible-vault")
        return DEPENDENCY_MISSING

    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    try:
        vault_env = read_env(vault_path, auth)
    except Exception as e:
        print(f"ERR: failed to read vault file {vault_path}: {e}")
        return SECRETS_FAILED

    child_env = os.environ.copy()
    for k, v in vault_env.items():
        child_env[str(k)] = str(v)

    try:
        r = subprocess.run(argv, env=child_env, check=False)
    except FileNotFoundError:
        print(f"ERR: command not found: {argv[0]}")
        return DEPENDENCY_MISSING
    except Exception as e:
        print(f"ERR: failed to run command: {e}")
        return SECRETS_FAILED
    return int(r.returncode)


__all__ = [
    "add_secrets_subparser",
    "run_akv_sync",
    "run_gsm_sync",
    "run_gsm_persist",
    "run_vault_sync",
    "run_set",
    "run_show",
    "run_exec",
    "run_ensure",
    "sync_gsm_to_runtime",
    "sync_hashicorp_vault_to_runtime",
    "resolve_default_gsm_map_file",
    "resolve_default_hashicorp_vault_map_file",
    "resolve_gsm_project_id",
    "SecretMapEntry",
]
