"""
purpose: Live-state skip guards for Hetzner Terragrunt modules.
Architecture Decision: ADR-N/A (terragrunt contracts)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hyops.runtime.credentials import discover_credential_env, parse_tfvars
from hyops.runtime.module_state import read_module_state

from .base import TerragruntModuleContract


def _resolve_hcloud_token(*, credentials_dir: Path | None, env: dict[str, str]) -> str:
    direct = str(env.get("HCLOUD_TOKEN") or "").strip()
    if direct:
        return direct

    exports: dict[str, str] = {}
    if credentials_dir is not None:
        exports = discover_credential_env(credentials_dir)

    tfvars_path_raw = str(
        env.get("HYOPS_HETZNER_TFVARS")
        or exports.get("HYOPS_HETZNER_TFVARS")
        or exports.get("HYOPS_HETZNER_CREDENTIALS_FILE")
        or ""
    ).strip()
    if not tfvars_path_raw:
        return ""

    values = parse_tfvars(Path(tfvars_path_raw).expanduser().resolve())
    return str(values.get("hcloud_token") or values.get("token") or "").strip()


def _server_id_fields(module_ref: str) -> tuple[tuple[str, str], ...]:
    if module_ref == "org/hetzner/vyos-edge-foundation":
        return (("edge01_id", "edge-a"), ("edge02_id", "edge-b"))
    if module_ref == "org/hetzner/shared-control-host":
        return (("vm_id", "shared-control-host"),)
    return ()


def _collect_published_server_ids(
    *,
    state_root: Path,
    module_ref: str,
    state_instance: str | None,
) -> tuple[list[tuple[str, str]], str]:
    try:
        state = read_module_state(state_root, module_ref, state_instance=state_instance)
    except FileNotFoundError:
        return [], ""
    except Exception as exc:
        return [], f"failed to read module state: {exc}"

    if str(state.get("status") or "").strip().lower() != "ok":
        return [], ""

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        return [], "module state is ok but published outputs are missing"

    found: list[tuple[str, str]] = []
    for field, label in _server_id_fields(module_ref):
        raw = str(outputs.get(field) or "").strip()
        if raw:
            found.append((label, raw))

    if found:
        return found, ""

    return [], "module state is ok but no Hetzner server ids were published"


def _server_exists(*, token: str, server_id: str) -> tuple[bool, str]:
    req = Request(
        f"https://api.hetzner.cloud/v1/servers/{server_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=5.0) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            if 200 <= code < 300:
                return True, ""
            return False, f"unexpected HTTP {code}"
    except HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code == 404:
            return False, ""
        return False, f"HTTP {code}"
    except URLError as exc:
        reason = str(getattr(exc, "reason", "") or exc).strip() or str(exc)
        return False, reason
    except Exception as exc:
        return False, str(exc)


class HetznerServerStateContract(TerragruntModuleContract):
    def evaluate_state_skip(
        self,
        *,
        command_name: str,
        module_ref: str,
        state_root: Path,
        state_instance: str | None,
        credentials_dir: Path | None,
        runtime_root: Path | None,
        env: dict[str, str],
    ) -> tuple[str, str]:
        del command_name, runtime_root

        fields = _server_id_fields(module_ref)
        if not fields:
            return "safe", ""

        published_ids, state_error = _collect_published_server_ids(
            state_root=state_root,
            module_ref=module_ref,
            state_instance=state_instance,
        )
        if state_error:
            return "stale", state_error
        if not published_ids:
            return "safe", ""

        token = _resolve_hcloud_token(credentials_dir=credentials_dir, env=env)
        if not token:
            return "error", (
                "unable to verify live Hetzner state before skip: HCLOUD_TOKEN is unavailable"
            )

        missing: list[str] = []
        for label, server_id in published_ids:
            exists, err = _server_exists(token=token, server_id=server_id)
            if err:
                return "error", (
                    f"unable to verify live Hetzner state for {label} server_id={server_id}: {err}"
                )
            if not exists:
                missing.append(f"{label}={server_id}")

        if missing:
            return "stale", (
                "published Hetzner server ids are missing from the live API: "
                + ", ".join(missing)
            )

        return "safe", ""
