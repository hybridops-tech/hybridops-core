"""hyops.validators.platform.onprem.eve_ng

purpose: Validate inputs for platform/onprem/eve-ng module.
Architecture Decision: ADR-N/A (onprem eve-ng validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return value


def _normalize_required_env(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("inputs.required_env must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"inputs.required_env[{idx}]"))
    return out


def _parse_os_release(payload: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (payload or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _read_target_os_release(
    *,
    target_host: str,
    target_user: str,
    target_port: int,
    ssh_private_key_file: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
) -> dict[str, str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        raise ValueError("missing command: ssh")

    argv = [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "LogLevel=ERROR",
        "-p",
        str(target_port),
    ]

    proxy_host = str(proxy_host or "").strip()
    if proxy_host:
        proxy_user = str(proxy_user or "").strip() or "root"
        if proxy_port < 1 or proxy_port > 65535:
            raise ValueError("inputs.ssh_proxy_jump_port must be between 1 and 65535")

        proxy_cmd_parts = [
            "ssh",
            "-p",
            str(int(proxy_port)),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
        if ssh_private_key_file:
            proxy_cmd_parts.extend(["-i", ssh_private_key_file, "-o", "IdentitiesOnly=yes"])
        proxy_cmd_parts.append(f"{proxy_user}@{proxy_host}")
        proxy_cmd_parts.extend(["nc", "%h", "%p"])
        proxy_cmd = " ".join(proxy_cmd_parts)

        argv.extend(["-o", f"ProxyCommand={proxy_cmd}"])

    if ssh_private_key_file:
        key_path = Path(ssh_private_key_file).expanduser()
        if not key_path.is_file():
            raise ValueError(f"inputs.ssh_private_key_file not found: {key_path}")
        argv.extend(["-i", str(key_path), "-o", "IdentitiesOnly=yes"])

    argv.extend([f"{target_user}@{target_host}", "cat /etc/os-release"])

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"ssh os check timed out after {exc.timeout}s (host={target_host})") from exc

    if int(proc.returncode) != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"rc={proc.returncode}"
        raise ValueError(f"ssh os check failed (host={target_host}): {detail}")

    return _parse_os_release(proc.stdout)


def _require_ubuntu_22(target_os: dict[str, str]) -> None:
    distro_id = str(target_os.get("ID") or "").strip().lower()
    version_id = str(target_os.get("VERSION_ID") or "").strip()
    codename = str(target_os.get("VERSION_CODENAME") or "").strip().lower()
    pretty = str(target_os.get("PRETTY_NAME") or "").strip()

    ok = distro_id == "ubuntu" and version_id.startswith("22.04")
    if ok:
        return

    detected = pretty or f"id={distro_id or 'unknown'} version_id={version_id or 'unknown'} codename={codename or 'unknown'}"
    raise ValueError(
        "EVE-NG role supports Ubuntu 22.04 (Jammy) only. "
        f"Detected: {detected}. "
        "Use a Jammy host, or use a different role/module for your OS."
    )


def validate(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")

    target_host = _require_non_empty_str(data.get("target_host"), "inputs.target_host")

    target_user = "root"
    if data.get("target_user") is not None:
        target_user = _require_non_empty_str(data.get("target_user"), "inputs.target_user")

    target_port = 22
    if data.get("target_port") is not None:
        target_port = _require_port(data.get("target_port"), "inputs.target_port")

    ssh_private_key_file = ""
    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        ssh_private_key_file = _require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")

    if data.get("become_user") is not None:
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    if data.get("load_vault_env") is not None and not isinstance(data.get("load_vault_env"), bool):
        raise ValueError("inputs.load_vault_env must be a boolean when set")

    required_env = _normalize_required_env(data.get("required_env"))

    proxy_host = str(data.get("ssh_proxy_jump_host") or "").strip()
    proxy_user = str(data.get("ssh_proxy_jump_user") or "").strip() or "root"
    proxy_port = 22
    if data.get("ssh_proxy_jump_port") is not None:
        proxy_port = _require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")

    profile = data.get("eveng_resource_profile")
    if profile is not None:
        token = str(profile or "").strip()
        if token and token not in ("minimal", "standard", "performance"):
            raise ValueError("inputs.eveng_resource_profile must be one of: minimal, standard, performance")

    eveng_root_password_env = _require_non_empty_str(data.get("eveng_root_password_env"), "inputs.eveng_root_password_env")
    eveng_admin_password_env = _require_non_empty_str(
        data.get("eveng_admin_password_env"), "inputs.eveng_admin_password_env"
    )

    missing_required_env = [k for k in (eveng_root_password_env, eveng_admin_password_env) if k not in required_env]
    if missing_required_env:
        missing = ", ".join(missing_required_env)
        raise ValueError(
            f"inputs.required_env must include: {missing} "
            f"(required because inputs.eveng_root_password_env and inputs.eveng_admin_password_env reference them)"
        )

    target_os = _read_target_os_release(
        target_host=target_host,
        target_user=target_user,
        target_port=target_port,
        ssh_private_key_file=ssh_private_key_file,
        proxy_host=proxy_host,
        proxy_user=proxy_user,
        proxy_port=proxy_port,
    )
    _require_ubuntu_22(target_os)
