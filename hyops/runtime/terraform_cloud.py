"""hyops.runtime.terraform_cloud

purpose: Shared Terraform Cloud helpers (config discovery + token discovery).
Architecture Decision: ADR-N/A (Terraform Cloud runtime integration)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import os
import re

from hyops.runtime.kv import read_kv_file


DEFAULT_TFC_HOST = "app.terraform.io"
DEFAULT_TFC_CREDENTIALS_FILE = "~/.terraform.d/credentials.tfrc.json"
DEFAULT_WORKSPACE_PREFIX = "hybridops"
_WORKSPACE_SAFE_RE = re.compile(r"[^a-z0-9_-]+")
_WORKSPACE_MAX_LEN = 90
_WORKSPACE_PREFIX_ALIASES: dict[str, tuple[str, ...]] = {
    "hybridops": ("platform",),
    "platform": ("hybridops",),
}


def normalize_workspace_name(value: str) -> str:
    ws = str(value or "").strip().lower()
    ws = _WORKSPACE_SAFE_RE.sub("-", ws)
    if not ws:
        return ""
    if len(ws) > _WORKSPACE_MAX_LEN:
        digest = hashlib.sha1(ws.encode("utf-8")).hexdigest()[:10]
        keep = max(_WORKSPACE_MAX_LEN - len(digest) - 1, 1)
        ws = f"{ws[:keep].rstrip('-')}-{digest}"
    return ws


def is_legacy_workspace_name_compatible(previous: str, current: str) -> bool:
    prior = str(previous or "").strip().lower()
    now = str(current or "").strip().lower()
    if not prior or not now or prior == now:
        return False
    if normalize_workspace_name(prior) == now:
        return True

    head, sep, tail = prior.partition("-")
    if not sep or not tail:
        return False

    for alias in _WORKSPACE_PREFIX_ALIASES.get(head, ()):
        candidate = normalize_workspace_name(f"{alias}-{tail}")
        if candidate == now:
            return True
    return False


@dataclass(frozen=True)
class TerraformCloudConfig:
    host: str
    org: str
    workspace_prefix: str
    credentials_file: Path
    config_path: Path


def runtime_config_path(runtime_root: Path) -> Path:
    return (runtime_root / "config" / "terraform-cloud.conf").resolve()


def resolve_config(
    *,
    config_path: Path,
    overrides: Mapping[str, str] | None = None,
) -> TerraformCloudConfig:
    cfg = read_kv_file(config_path)
    o = overrides or {}

    host = str(o.get("TFC_HOST") or cfg.get("TFC_HOST") or DEFAULT_TFC_HOST).strip() or DEFAULT_TFC_HOST
    org = str(o.get("TFC_ORG") or cfg.get("TFC_ORG") or "").strip()
    workspace_prefix = str(
        o.get("WORKSPACE_PREFIX") or cfg.get("WORKSPACE_PREFIX") or DEFAULT_WORKSPACE_PREFIX
    ).strip() or DEFAULT_WORKSPACE_PREFIX

    cred_raw = str(
        o.get("TFC_CREDENTIALS_FILE") or cfg.get("TFC_CREDENTIALS_FILE") or DEFAULT_TFC_CREDENTIALS_FILE
    ).strip() or DEFAULT_TFC_CREDENTIALS_FILE
    credentials_file = Path(os.path.expanduser(cred_raw)).resolve()

    return TerraformCloudConfig(
        host=host,
        org=org,
        workspace_prefix=workspace_prefix,
        credentials_file=credentials_file,
        config_path=config_path.resolve(),
    )


def apply_runtime_config_env(env: dict[str, str], runtime_root: Path) -> None:
    """Apply per-env Terraform Cloud config to env (without overriding explicit values)."""

    config_path = runtime_config_path(runtime_root)
    if not config_path.exists():
        return

    cfg = read_kv_file(config_path)
    for key in ("TFC_HOST", "TFC_ORG", "TFC_CREDENTIALS_FILE", "WORKSPACE_PREFIX"):
        value = str(cfg.get(key) or "").strip()
        if not value:
            continue
        # Preserve explicit operator env (highest precedence).
        if str(env.get(key) or "").strip():
            continue
        env[key] = value


def tf_token_env_key(host: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z]", "_", (host or "").strip() or DEFAULT_TFC_HOST)
    return f"TF_TOKEN_{safe}"


def read_tfrc_token(credentials_file: Path, host: str) -> str | None:
    cred_file = credentials_file.expanduser().resolve()
    if not cred_file.exists():
        return None

    try:
        data = json.loads(cred_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    creds = data.get("credentials")
    if not isinstance(creds, dict):
        return None

    host_data = creds.get(host)
    if not isinstance(host_data, dict):
        return None

    token = host_data.get("token")
    if not isinstance(token, str):
        return None

    token = token.strip()
    return token or None


def require_tfrc_token(host: str, credentials_file: Path) -> str:
    host_name = (host or "").strip()
    if not host_name:
        raise ValueError("tfc host is required")

    cred_file = credentials_file.expanduser().resolve()
    if not cred_file.exists():
        raise FileNotFoundError(f"terraform credentials file not found: {cred_file}")

    try:
        data = json.loads(cred_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("invalid terraform credentials file: not valid JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("invalid terraform credentials file: expected JSON object")

    creds = data.get("credentials")
    if not isinstance(creds, dict):
        raise ValueError("invalid terraform credentials file: missing credentials object")

    host_entry = creds.get(host_name)
    if not isinstance(host_entry, dict):
        raise ValueError(f"terraform credentials missing host entry: {host_name}")

    token = host_entry.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError(f"terraform credentials missing token for host: {host_name}")

    return token.strip()


def write_tfrc_token(credentials_file: Path, host: str, token: str) -> None:
    credentials_file.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}
    if credentials_file.exists():
        try:
            raw = json.loads(credentials_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}

    creds = data.get("credentials")
    if not isinstance(creds, dict):
        creds = {}
    data["credentials"] = creds
    creds[host] = {"token": token}

    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    credentials_file.write_text(payload, encoding="utf-8")
    os.chmod(credentials_file, 0o600)


def find_token(*, env: Mapping[str, str], host: str, credentials_file: Path) -> str | None:
    key = tf_token_env_key(host)
    token = str(env.get(key) or "").strip()
    if token:
        return token
    return read_tfrc_token(credentials_file, host)


def preflight_cloud_backend(*, env: Mapping[str, str], runtime_root: Path, env_name: str) -> str:
    """Fail-fast checks for Terraform Cloud backend before running terraform/terragrunt init."""

    host = str(env.get("TFC_HOST") or DEFAULT_TFC_HOST).strip() or DEFAULT_TFC_HOST
    org = str(env.get("TFC_ORG") or "").strip()

    cred_file_raw = str(env.get("TFC_CREDENTIALS_FILE") or DEFAULT_TFC_CREDENTIALS_FILE).strip()
    credentials_file = Path(os.path.expanduser(cred_file_raw)).resolve()

    config_path = runtime_config_path(runtime_root)
    if config_path.exists():
        try:
            cfg = read_kv_file(config_path)
        except Exception as exc:
            return f"Terraform Cloud backend selected but failed to read config: {config_path} ({exc})"

        if not str(cfg.get("TFC_ORG") or "").strip():
            hint_env = f" --env {env_name}" if env_name else ""
            return (
                f"Terraform Cloud backend selected but TFC_ORG is empty in {config_path}. "
                f"Run: hyops init terraform-cloud{hint_env} and set TFC_ORG. "
                "Or switch to local state: export HYOPS_TERRAFORM_BACKEND_MODE=local"
            )

    if not org:
        hint_env = f" --env {env_name}" if env_name else ""
        return (
            "Terraform Cloud backend selected but TFC_ORG is not set. "
            f"Set it in {config_path} (run: hyops init terraform-cloud{hint_env}) or export TFC_ORG, "
            "or switch to local state: export HYOPS_TERRAFORM_BACKEND_MODE=local"
        )

    token = find_token(env=env, host=host, credentials_file=credentials_file) or ""
    if not token:
        token_key = tf_token_env_key(host)
        hint_env = f" --env {env_name}" if env_name else ""
        return (
            "Terraform Cloud backend selected but no Terraform Cloud token was found. "
            f"Expected either {token_key} or a token in {credentials_file} for host={host}. "
            f"Fix: run hyops init terraform-cloud{hint_env} --with-cli-login (recommended) or run: terraform login {host}. "
            "Or switch to local state: export HYOPS_TERRAFORM_BACKEND_MODE=local"
        )

    return ""


def _workspace_target_suffix(*, module_ref: str, inputs: Mapping[str, Any]) -> str:
    """Return an optional deterministic workspace discriminator for risky replacement cases.

    Most modules should keep one stable workspace per env/module pair.
    Some bootstrap modules, such as GCP project factory, manage resources whose
    identity should never be treated as an in-place replacement target across
    unrelated accounts or projects. In those cases we include the durable target
    identity in the workspace name so a new project gets a new workspace/state.
    """

    ref = str(module_ref or "").strip().lower()
    if ref == "org/gcp/project-factory":
        project_id = str(inputs.get("project_id") or "").strip().lower()
        if project_id:
            return project_id
    return ""


def derive_workspace_name(
    *,
    provider: str,
    module_ref: str,
    pack_id: str,
    inputs: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    env_name: str = "",
    naming_policy: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Derive a Terraform Cloud workspace name (provider-safe)."""

    provider_token = str(provider or "").strip().lower()
    if not provider_token:
        return "", "workspace provider is required"

    env_map: Mapping[str, str] = env if isinstance(env, Mapping) else {}

    name_prefix = str(inputs.get("name_prefix") or "").strip()
    if not name_prefix:
        name_prefix = str(env_map.get("WORKSPACE_PREFIX") or DEFAULT_WORKSPACE_PREFIX).strip()

    context_id = str(inputs.get("context_id") or "").strip()
    if not context_id:
        context_id = str(env_name or env_map.get("HYOPS_ENV") or "").strip()

    module_id = module_ref.replace("/", "__") if module_ref else "unknown_module"
    module_component = module_id.replace("_", "-")
    pack_component = (pack_id or "").replace("/", "-").replace("@", "-")

    tokens = {
        "name_prefix": name_prefix,
        "provider": provider_token,
        "context_id": context_id,
        "module": module_component,
        "pack": pack_component,
    }
    target_suffix = _workspace_target_suffix(module_ref=module_ref, inputs=inputs)

    raw_policy = naming_policy if isinstance(naming_policy, Mapping) else {}
    pattern = str(raw_policy.get("workspace_pattern") or "").strip()
    if pattern:
        raw = pattern
        for key, value in tokens.items():
            raw = raw.replace("{" + key + "}", value)
        raw = raw.replace("{target}", target_suffix)
        ws_raw = raw
    else:
        ws_raw = "-".join(
            [p for p in (name_prefix, provider_token, context_id, module_component, pack_component, target_suffix) if p]
        )

    ws = normalize_workspace_name(ws_raw)
    if not ws:
        return "", "failed to derive workspace name"

    return ws, ""
