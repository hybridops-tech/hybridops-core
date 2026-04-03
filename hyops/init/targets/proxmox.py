"""
purpose: Implement `hyops init proxmox` and produce readiness + credentials.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import configparser
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from typing import Iterator
import os
from pathlib import Path
import re
import shlex
import shutil
from urllib.parse import urlparse

from hyops.runtime.config import write_template_if_missing
from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.exitcodes import (
    OK,
    TEMPLATE_WRITTEN,
    CONFIG_INVALID,
    DEPENDENCY_MISSING,
    REMOTE_FAILED,
    SECRETS_FAILED,
    INTERNAL_ERROR,
)
from hyops.init.helpers import init_evidence_path, init_run_id
from hyops.init.shared_args import add_init_shared_args
from hyops.runtime.layout import ensure_layout, ensure_parent
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.proc import run as run_proc, run_capture, run_capture_sensitive
from hyops.runtime.readiness import read_marker, write_marker
from hyops.runtime.stamp import stamp_runtime
from hyops.runtime.vault import VaultAuth, has_password_source, merge_set, read_env


_TEMPLATE = """# purpose: Proxmox init configuration for HybridOps.Core
# maintainer: HybridOps.Tech

[proxmox]
host = pve.example.local
port = 8006

user_fq = automation@pam
token_name = infra-token
api_token_id =

fallback_storage_vm = local-lvm
fallback_storage_iso = local
fallback_storage_snippets = local
fallback_bridge = vmbr0

tls_skip = true
http_port = 8802

ssh_username = root
ssh_private_key = ~/.ssh/id_ed25519
ssh_public_key =
http_bind_address =
"""

SSH_OPTS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "LogLevel=ERROR",
]

_REMOTE_BOOTSTRAP_ASSET = "bootstrap-proxmox-remote.sh"
_REMOTE_BOOTSTRAP_DEST = "/tmp/hyops-bootstrap-proxmox-remote.sh"


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("proxmox", help="Initialise Proxmox target runtime and credentials.")

    add_init_shared_args(p)

    p.add_argument("--host", default=None, help="Override proxmox.host from config.")
    p.add_argument("--proxmox-ip", dest="host", default=None, help="Alias of --host.")
    p.add_argument("--user-fq", default=None, help="Override proxmox.user_fq from config.")
    p.add_argument("--token-name", default=None, help="Override proxmox.token_name from config.")
    p.add_argument("--tls-skip", default=None, choices=["true", "false"], help="Override proxmox.tls_skip from config.")
    p.add_argument("--http-port", default=None, help="Override proxmox.http_port from config.")
    p.add_argument("--ssh-username", default=None, help="Override proxmox.ssh_username from config.")
    p.add_argument("--ssh-private-key", default=None, help="Override proxmox.ssh_private_key from config.")
    p.add_argument("--ssh-public-key", default=None, help="Override proxmox.ssh_public_key from config.")
    p.add_argument("--http-bind-address", default=None, help="Override proxmox.http_bind_address from config.")

    p.add_argument("--remote-bootstrap", default=None, help="Override remote bootstrap script path.")
    p.add_argument("--bootstrap", action="store_true", help="Run remote bootstrap immediately after config validation.")
    p.add_argument("--no-remote", action="store_true", help="Skip remote bootstrap.")
    p.set_defaults(_handler=run)


def _default_config_path(runtime_root: Path) -> Path:
    return runtime_root / "config" / "proxmox.conf"


def _default_vault_path(runtime_root: Path) -> Path:
    return runtime_root / "vault" / "bootstrap.vault.env"


def _default_credentials_path(runtime_root: Path) -> Path:
    return runtime_root / "credentials" / "proxmox.credentials.tfvars"


def _need_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _read_first_pubkey() -> str:
    home = Path.home()
    for p in (home / ".ssh" / "id_ed25519.pub", home / ".ssh" / "id_rsa.pub"):
        try:
            if p.exists():
                v = p.read_text(encoding="utf-8").strip()
                if v:
                    return v
        except Exception:
            continue
    return ""


def _detect_workstation_ip(target_host: str) -> str:
    r = run_proc(["ip", "route", "get", target_host], timeout_s=5)
    if r.rc == 0:
        m = re.search(r"\bsrc\s+([0-9.]+)\b", r.stdout or "")
        if m:
            return m.group(1)

    r = run_proc(["hostname", "-I"], timeout_s=5)
    if r.rc == 0:
        parts = (r.stdout or "").strip().split()
        if parts:
            return parts[0]
    return ""


def _local_ipv4_addresses() -> set[str]:
    r = run_proc(["ip", "-4", "-o", "addr", "show", "scope", "global"], timeout_s=5)
    if r.rc != 0:
        return set()
    ips: set[str] = set()
    for raw in (r.stdout or "").splitlines():
        m = re.search(r"\binet\s+([0-9.]+)/\d+\b", raw)
        if m:
            ips.add(m.group(1))
    return ips


def _is_valid_http_bind_address(value: str) -> bool:
    addr = str(value or "").strip()
    if not addr:
        return False
    if addr == "0.0.0.0":
        return True
    return addr in _local_ipv4_addresses()


def _parse_exports(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("EXPORT:"):
            continue
        kv = line[len("EXPORT:") :]
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _validate_port(field_name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing required proxmox.{field_name}")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"proxmox.{field_name} must be an integer") from exc
    if parsed < 1 or parsed > 65535:
        raise ValueError(f"proxmox.{field_name} must be in range 1..65535")
    return str(parsed)


def _validate_bool(field_name: str, value: str) -> str:
    text = str(value or "").strip().lower()
    if text in ("true", "1", "yes"):
        return "true"
    if text in ("false", "0", "no"):
        return "false"
    raise ValueError(f"proxmox.{field_name} must be one of: true,false,1,0,yes,no")


def _load_and_validate(cfg_path: Path) -> dict[str, str]:
    c = configparser.ConfigParser()
    c.read(cfg_path)
    if "proxmox" not in c:
        raise ValueError("missing [proxmox] section")

    s = c["proxmox"]
    for k in ("host", "user_fq"):
        if not s.get(k, "").strip():
            raise ValueError(f"missing required proxmox.{k}")

    fallback_iso = s.get("fallback_storage_iso", "local").strip()
    fallback_snippets = s.get("fallback_storage_snippets", "").strip() or fallback_iso
    tls_skip = _validate_bool("tls_skip", s.get("tls_skip", "true"))
    port = _validate_port("port", s.get("port", "8006"))
    http_port = _validate_port("http_port", s.get("http_port", "8802"))

    return {
        "host": s.get("host", "").strip(),
        "port": port,
        "user_fq": s.get("user_fq", "").strip(),
        "token_name": s.get("token_name", "infra-token").strip(),
        "api_token_id": s.get("api_token_id", "").strip(),
        "fallback_storage_vm": s.get("fallback_storage_vm", "local-lvm").strip(),
        "fallback_storage_iso": fallback_iso,
        "fallback_storage_snippets": fallback_snippets,
        "fallback_bridge": s.get("fallback_bridge", "vmbr0").strip(),
        "tls_skip": tls_skip,
        "http_port": http_port,
        "ssh_username": s.get("ssh_username", "root").strip(),
        "ssh_private_key": s.get("ssh_private_key", "~/.ssh/id_ed25519").strip(),
        "ssh_public_key": s.get("ssh_public_key", "").strip(),
        "http_bind_address": s.get("http_bind_address", "").strip(),
    }


def _apply_overrides(values: dict[str, str], ns) -> dict[str, str]:
    out = dict(values)
    if ns.host:
        out["host"] = ns.host
    if ns.user_fq:
        out["user_fq"] = ns.user_fq
    if ns.token_name:
        out["token_name"] = ns.token_name
    if ns.tls_skip:
        out["tls_skip"] = ns.tls_skip
    if ns.http_port:
        out["http_port"] = ns.http_port
    if ns.ssh_username:
        out["ssh_username"] = ns.ssh_username
    if ns.ssh_private_key:
        out["ssh_private_key"] = ns.ssh_private_key
    if ns.ssh_public_key:
        out["ssh_public_key"] = ns.ssh_public_key
    if ns.http_bind_address:
        out["http_bind_address"] = ns.http_bind_address
    return out


def _normalize_values(values: dict[str, str]) -> dict[str, str]:
    out = dict(values)
    for key in ("host", "user_fq"):
        if not str(out.get(key, "")).strip():
            raise ValueError(f"missing required proxmox.{key}")
    out["port"] = _validate_port("port", out.get("port", "8006"))
    out["http_port"] = _validate_port("http_port", out.get("http_port", "8802"))
    out["tls_skip"] = _validate_bool("tls_skip", out.get("tls_skip", "true"))
    return out


def _derive_token_id(values: dict[str, str]) -> str:
    if values.get("api_token_id"):
        return values["api_token_id"]
    return f'{values["user_fq"]}!{values["token_name"]}'


def _runtime_envs_root(runtime_root: Path) -> Path:
    """Return ~/.hybridops/envs root when runtime_root matches that layout."""
    rr = runtime_root.resolve()
    parent = rr.parent.resolve()
    if parent.name == "envs":
        return parent
    return (Path.home() / ".hybridops" / "envs").resolve()


def _parse_proxmox_url_host_port(raw_url: str) -> tuple[str, str]:
    raw = str(raw_url or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return "", ""
    host = str(parsed.hostname or "").strip()
    port = str(parsed.port or "").strip()
    return host, port


def _backfill_values_from_local_runtime(
    values: dict[str, str],
    *,
    meta_dir: Path,
    cred_path: Path,
) -> dict[str, str]:
    """Recover stable proxmox init values from existing local readiness/credentials."""
    out = dict(values)

    try:
        marker = read_marker(meta_dir, "proxmox")
    except Exception:
        marker = {}

    context = marker.get("context") if isinstance(marker.get("context"), dict) else {}
    runtime = marker.get("runtime") if isinstance(marker.get("runtime"), dict) else {}

    if str(out.get("host") or "").strip() == "pve.example.local":
        recovered_host = str(runtime.get("api_ip") or "").strip()
        if not recovered_host and cred_path.is_file():
            try:
                tfvars = parse_tfvars(cred_path)
            except Exception:
                tfvars = {}
            recovered_host, recovered_port = _parse_proxmox_url_host_port(str(tfvars.get("proxmox_url") or ""))
            if recovered_port and not str(out.get("port") or "").strip():
                out["port"] = recovered_port
        if recovered_host:
            out["host"] = recovered_host

    if not str(out.get("ssh_public_key") or "").strip():
        recovered_key = str(context.get("ssh_public_key") or "").strip()
        if not recovered_key and cred_path.is_file():
            try:
                tfvars = parse_tfvars(cred_path)
            except Exception:
                tfvars = {}
            recovered_key = str(tfvars.get("ssh_public_key") or "").strip()
        if not recovered_key:
            recovered_key = _read_first_pubkey()
        if recovered_key:
            out["ssh_public_key"] = recovered_key

    if not str(out.get("http_bind_address") or "").strip() and cred_path.is_file():
        try:
            tfvars = parse_tfvars(cred_path)
        except Exception:
            tfvars = {}
        recovered_bind = str(tfvars.get("http_bind_address") or "").strip()
        if _is_valid_http_bind_address(recovered_bind):
            out["http_bind_address"] = recovered_bind

    return out


def _find_reusable_proxmox_token_secret(
    *,
    runtime_root: Path,
    target_host: str,
    target_port: str,
    token_id: str,
    tls_skip: str,
    auth: VaultAuth,
    evidence_dir: Path,
) -> tuple[str, str]:
    """Find a valid PROXMOX_TOKEN_SECRET from sibling envs for same host/token."""
    envs_root = _runtime_envs_root(runtime_root)
    if not envs_root.is_dir():
        return "", ""

    current_root = runtime_root.resolve()
    for env_dir in sorted(envs_root.iterdir(), key=lambda p: p.name):
        if not env_dir.is_dir():
            continue
        if env_dir.resolve() == current_root:
            continue

        cred_path = (env_dir / "credentials" / "proxmox.credentials.tfvars").resolve()
        vault_path = (env_dir / "vault" / "bootstrap.vault.env").resolve()
        if not cred_path.is_file():
            continue

        try:
            tfvars = parse_tfvars(cred_path)
        except Exception:
            continue
        candidate_token_id = str(tfvars.get("proxmox_token_id") or "").strip()
        if not candidate_token_id or candidate_token_id != token_id:
            continue

        candidate_host, candidate_port = _parse_proxmox_url_host_port(
            str(tfvars.get("proxmox_url") or "")
        )
        if not candidate_host:
            continue
        if candidate_host.lower() != str(target_host or "").strip().lower():
            continue
        if str(target_port or "").strip() and str(candidate_port or "").strip():
            if str(target_port).strip() != str(candidate_port).strip():
                continue

        candidate_secrets: list[str] = []
        tfvars_secret = str(tfvars.get("proxmox_token_secret") or "").strip()
        if tfvars_secret:
            candidate_secrets.append(tfvars_secret)

        if vault_path.is_file():
            try:
                env_map = read_env(vault_path, auth)
            except Exception:
                env_map = {}
            vault_secret = str(env_map.get("PROXMOX_TOKEN_SECRET") or "").strip()
            if vault_secret and vault_secret not in candidate_secrets:
                candidate_secrets.append(vault_secret)

        for candidate_secret in candidate_secrets:
            ok = _validate_api_token(
                evidence_dir=evidence_dir,
                api_ip=str(target_host or "").strip(),
                api_port=str(target_port or "").strip() or "8006",
                tls_skip=str(tls_skip or "").strip() or "true",
                token_id=token_id,
                token_secret=candidate_secret,
            )
            if ok:
                return candidate_secret, env_dir.name

    return "", ""


def _validate_api_token(
    *,
    evidence_dir: Path,
    api_ip: str,
    api_port: str,
    tls_skip: str,
    token_id: str,
    token_secret: str,
) -> bool:
    return _validate_api_endpoint(
        evidence_dir=evidence_dir,
        api_ip=api_ip,
        api_port=api_port,
        tls_skip=tls_skip,
        token_id=token_id,
        token_secret=token_secret,
        api_path="/version",
        label="proxmox_api_token_check",
    )


def _validate_api_endpoint(
    *,
    evidence_dir: Path,
    api_ip: str,
    api_port: str,
    tls_skip: str,
    token_id: str,
    token_secret: str,
    api_path: str,
    label: str,
) -> bool:
    api_url = f"https://{api_ip}:{api_port}/api2/json/version"
    api_suffix = str(api_path or "").strip()
    if api_suffix and not api_suffix.startswith("/"):
        api_suffix = f"/{api_suffix}"
    if api_suffix:
        api_url = f"https://{api_ip}:{api_port}/api2/json{api_suffix}"
    curl_tls_opt = "-k" if str(tls_skip or "").strip().lower() in ("true", "1", "yes") else ""
    env = os.environ.copy()
    env.update(
        {
            "HYOPS_PVE_API_URL": api_url,
            "HYOPS_PVE_TOKEN_ID": token_id,
            "HYOPS_PVE_TOKEN_SECRET": token_secret,
            "HYOPS_PVE_CURL_TLS_OPT": curl_tls_opt,
        }
    )
    r = run_capture(
        [
            "/bin/bash",
            "-lc",
            'curl -fsS ${HYOPS_PVE_CURL_TLS_OPT} -o /dev/null '
            '-H "Authorization: PVEAPIToken=${HYOPS_PVE_TOKEN_ID}=${HYOPS_PVE_TOKEN_SECRET}" '
            '"${HYOPS_PVE_API_URL}"',
        ],
        evidence_dir=evidence_dir,
        label=label,
        env=env,
        timeout_s=20,
        redact=True,
    )
    return r.rc == 0


def _validate_storage_content_access(
    *,
    evidence_dir: Path,
    api_ip: str,
    api_port: str,
    tls_skip: str,
    token_id: str,
    token_secret: str,
    node: str,
    datastore: str,
) -> bool:
    node_name = str(node or "").strip()
    datastore_id = str(datastore or "").strip()
    if not node_name or not datastore_id:
        return False
    return _validate_api_endpoint(
        evidence_dir=evidence_dir,
        api_ip=api_ip,
        api_port=api_port,
        tls_skip=tls_skip,
        token_id=token_id,
        token_secret=token_secret,
        api_path=f"/nodes/{node_name}/storage/{datastore_id}/content",
        label=f"proxmox_api_storage_{datastore_id}_content_check",
    )


def _has_vault_password_source(ns) -> bool:
    auth = VaultAuth(
        password_file=getattr(ns, "vault_password_file", None),
        password_command=getattr(ns, "vault_password_command", None),
    )
    return has_password_source(auth)


def _bootstrap_ssh_opts(values: dict[str, str]) -> list[str]:
    opts = list(SSH_OPTS)
    key_path = str(values.get("ssh_private_key") or "").strip()
    if not key_path:
        return opts
    resolved = Path(key_path).expanduser()
    return ["-i", str(resolved), *opts]


def _write_tfvars(
    path: Path,
    values: dict[str, str],
    token_id: str,
    token_secret: str,
    runtime: dict[str, str],
) -> dict[str, str]:
    ensure_parent(path)

    tls_skip = "true" if values.get("tls_skip", "true") in ("true", "1", "yes") else "false"
    ssh_public_key = values.get("ssh_public_key", "").strip() or _read_first_pubkey()
    ssh_private_key = values.get("ssh_private_key", "").strip()
    ssh_username = values.get("ssh_username", "root").strip()
    http_bind_address = values.get("http_bind_address", "").strip()
    if not _is_valid_http_bind_address(http_bind_address):
        http_bind_address = _detect_workstation_ip(values["host"])
    http_port = values.get("http_port", "8802").strip()
    api_port = values.get("port", "8006").strip()

    lines = [
        "# <sensitive> Do not commit.",
        "# purpose: Proxmox runtime inputs for infrastructure and image drivers.",
        "# maintainer: HybridOps.Tech",
        "# </sensitive>",
        "",
        f'proxmox_url          = "https://{runtime["api_ip"]}:{api_port}/api2/json"',
        f'proxmox_token_id     = "{token_id}"',
        f'proxmox_token_secret = "{token_secret}"',
        f'proxmox_node         = "{runtime["node"]}"',
        f"proxmox_skip_tls     = {tls_skip}",
        "",
        f'proxmox_ssh_username = "{ssh_username}"',
        f'proxmox_ssh_key      = "{ssh_private_key}"',
        "",
        f'storage_pool     = "{runtime["storage_vm"]}"',
        f'storage_iso      = "{runtime["storage_iso"]}"',
        f'storage_snippets = "{runtime["storage_snippets"]}"',
        "",
        f'network_bridge = "{runtime["bridge"]}"',
        "",
        f'http_bind_address = "{http_bind_address}"',
        f"http_port         = {http_port}",
        "",
        f'ssh_public_key = "{ssh_public_key}"',
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(path, 0o600)
    return {
        "ssh_public_key": ssh_public_key,
        "http_bind_address": http_bind_address,
        "http_port": http_port,
    }


@contextmanager
def _remote_script_path() -> Iterator[Path]:
    ref = resources.files("hyops.assets.init.proxmox").joinpath(_REMOTE_BOOTSTRAP_ASSET)
    with resources.as_file(ref) as p:
        yield p


def run(ns) -> int:
    target = "proxmox"
    run_id = init_run_id("init-proxmox")

    if bool(getattr(ns, "bootstrap", False)) and bool(getattr(ns, "no_remote", False)):
        print("invalid flags: --bootstrap and --no-remote cannot be used together")
        return CONFIG_INVALID

    paths = resolve_runtime_paths(ns.root, getattr(ns, "env", None))
    ensure_layout(paths)

    cfg_path = Path(ns.config).expanduser() if ns.config else _default_config_path(paths.root)
    vault_path = Path(ns.vault_file).expanduser() if ns.vault_file else _default_vault_path(paths.root)
    cred_path = _default_credentials_path(paths.root)

    out_dir = getattr(ns, "out_dir", None)
    evidence_dir = init_evidence_path(paths.root, out_dir, target, run_id)

    ev = EvidenceWriter(evidence_dir)

    ev.write_json(
        "meta.json",
        {
            "target": target,
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "paths": {
                "runtime_root": str(paths.root),
                "config": str(cfg_path),
                "vault": str(vault_path),
                "credentials": str(cred_path),
                "evidence_dir": str(evidence_dir),
            },
            "flags": {
                "non_interactive": bool(getattr(ns, "non_interactive", False)),
                "force": bool(getattr(ns, "force", False)),
                "dry_run": bool(getattr(ns, "dry_run", False)),
                "bootstrap": bool(getattr(ns, "bootstrap", False)),
                "no_remote": bool(getattr(ns, "no_remote", False)),
            },
        },
    )

    try:
        stamp_runtime(
            paths.root,
            command="init",
            target=target,
            run_id=run_id,
            evidence_dir=evidence_dir,
            extra={
                "config": str(cfg_path),
                "vault": str(vault_path),
                "credentials": str(cred_path),
                "out_dir": str(out_dir or ""),
                "mode": {
                    "non_interactive": bool(getattr(ns, "non_interactive", False)),
                    "dry_run": bool(getattr(ns, "dry_run", False)),
                    "force": bool(getattr(ns, "force", False)),
                },
            },
        )
    except Exception:
        pass

    template_written = write_template_if_missing(cfg_path, _TEMPLATE)
    if template_written:
        print(f"wrote config template: {cfg_path}")
        if not bool(getattr(ns, "bootstrap", False)):
            print("edit the file and re-run: hyops init proxmox")
            print("or run bootstrap directly: hyops init proxmox --bootstrap --host <proxmox-ip>")
            return TEMPLATE_WRITTEN
        print("config template created; continuing with bootstrap using CLI overrides.")

    try:
        values = _normalize_values(
            _backfill_values_from_local_runtime(
                _apply_overrides(_load_and_validate(cfg_path), ns),
                meta_dir=paths.meta_dir,
                cred_path=cred_path,
            )
        )
    except Exception as e:
        print(f"config invalid: {e}")
        return CONFIG_INVALID

    need_vault = bool(
        vault_path.exists()
        or getattr(ns, "vault_password_file", None)
        or getattr(ns, "vault_password_command", None)
        or bool(getattr(ns, "non_interactive", False))
        or bool(getattr(ns, "force", False))
    )
    has_vault_password = _has_vault_password_source(ns)

    for cmd in ("ssh", "scp", "curl"):
        if not _need_cmd(cmd):
            print(f"missing command: {cmd}")
            return DEPENDENCY_MISSING
    if need_vault and not _need_cmd("ansible-vault"):
        print("missing command: ansible-vault")
        return DEPENDENCY_MISSING

    auth = VaultAuth(password_file=ns.vault_password_file, password_command=ns.vault_password_command)

    token_secret = ""
    if need_vault:
        if not has_vault_password:
            print("vault password source required; pass --vault-password-file or --vault-password-command")
            return SECRETS_FAILED
        try:
            env = read_env(vault_path, auth) if vault_path.exists() else {}
            token_secret = (env.get("PROXMOX_TOKEN_SECRET") or "").strip()
        except Exception as e:
            print(f"vault read failed: {e}")
            return SECRETS_FAILED

    token_id = _derive_token_id(values)
    want_remote = bool(getattr(ns, "bootstrap", False)) or not bool(getattr(ns, "no_remote", False))

    # If this env carries a stale token for the same shared Proxmox target,
    # prefer healing from a valid sibling env token before rotating remotely.
    if (
        want_remote
        and token_secret
        and not bool(getattr(ns, "force", False))
        and has_vault_password
        and not _validate_api_token(
            evidence_dir=evidence_dir,
            api_ip=str(values.get("host") or "").strip(),
            api_port=str(values.get("port") or "8006").strip(),
            tls_skip=str(values.get("tls_skip") or "true"),
            token_id=token_id,
            token_secret=token_secret,
        )
    ):
        reusable_secret, reusable_env = _find_reusable_proxmox_token_secret(
            runtime_root=paths.root,
            target_host=str(values.get("host") or "").strip(),
            target_port=str(values.get("port") or "8006").strip(),
            token_id=token_id,
            tls_skip=str(values.get("tls_skip") or "true"),
            auth=auth,
            evidence_dir=evidence_dir,
        )
        if reusable_secret and reusable_env:
            token_secret = reusable_secret
            try:
                merge_set(vault_path, auth, {"PROXMOX_TOKEN_SECRET": token_secret})
            except Exception as e:
                print(f"vault write failed: {e}")
                return SECRETS_FAILED
            print(
                f"reused PROXMOX_TOKEN_SECRET from env '{reusable_env}' "
                f"because the current env token for {token_id} is no longer valid"
            )
        else:
            token_secret = ""
            print(
                f"configured PROXMOX_TOKEN_SECRET for {token_id} is no longer valid; "
                "refreshing it via remote bootstrap"
            )

    # Guard against accidental token rotation across envs:
    # if this env has no token yet, attempt to reuse a valid token from another
    # env targeting the same Proxmox host + token_id.
    if (
        want_remote
        and not token_secret
        and not bool(getattr(ns, "force", False))
        and has_vault_password
    ):
        reusable_secret, reusable_env = _find_reusable_proxmox_token_secret(
            runtime_root=paths.root,
            target_host=str(values.get("host") or "").strip(),
            target_port=str(values.get("port") or "8006").strip(),
            token_id=token_id,
            tls_skip=str(values.get("tls_skip") or "true"),
            auth=auth,
            evidence_dir=evidence_dir,
        )
        if reusable_secret and reusable_env:
            use_reusable = True
            if not bool(getattr(ns, "non_interactive", False)):
                target_env = str(paths.root.name or "").strip() or "<current>"
                print(
                    f"found a valid Proxmox token in env '{reusable_env}' for "
                    f"{values.get('host')} ({token_id})"
                )
                try:
                    answer = input(
                        f"reuse this token for env '{target_env}' to avoid rotation? [Y/n]: "
                    ).strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("cancelled")
                    return SECRETS_FAILED
                if answer in ("n", "no"):
                    use_reusable = False
            if use_reusable:
                token_secret = reusable_secret
                try:
                    merge_set(vault_path, auth, {"PROXMOX_TOKEN_SECRET": token_secret})
                except Exception as e:
                    print(f"vault write failed: {e}")
                    return SECRETS_FAILED
                print(
                    f"reused PROXMOX_TOKEN_SECRET from env '{reusable_env}' "
                    f"to avoid rotating token {token_id}"
                )

    if getattr(ns, "non_interactive", False) and not token_secret:
        print("non-interactive requires PROXMOX_TOKEN_SECRET in the vault")
        return SECRETS_FAILED

    runtime = {
        "node": "",
        "api_ip": values["host"],
        "storage_vm": values["fallback_storage_vm"],
        "storage_iso": values["fallback_storage_iso"],
        "storage_snippets": values["fallback_storage_snippets"],
        "bridge": values["fallback_bridge"],
        "storage_vm_source": "fallback",
        "storage_iso_source": "fallback",
        "storage_snippets_source": "fallback",
        "bridge_source": "fallback",
    }

    if want_remote and values.get("host") == "pve.example.local":
        print("bootstrap requires a real Proxmox host; pass --host/--proxmox-ip or edit config")
        return CONFIG_INVALID

    if want_remote and ((not token_secret) or bool(getattr(ns, "force", False))) and not has_vault_password:
        print("vault password source required to persist bootstrap token; pass --vault-password-file or --vault-password-command")
        return SECRETS_FAILED

    ssh_username = (values.get("ssh_username") or "root").strip() or "root"
    ssh_opts = _bootstrap_ssh_opts(values)
    if values.get("ssh_private_key"):
        key_path = Path(values["ssh_private_key"]).expanduser()
        if not key_path.exists():
            print(f"ssh private key not found: {key_path}")
            return CONFIG_INVALID

    if getattr(ns, "non_interactive", False) and token_secret and not bool(getattr(ns, "bootstrap", False)):
        try:
            existing = read_marker(paths.meta_dir, target)
            rt = existing.get("runtime", {})
            if isinstance(rt, dict) and rt.get("node") and rt.get("api_ip"):
                runtime.update(
                    {
                        "node": str(rt.get("node", "")),
                        "api_ip": str(rt.get("api_ip", runtime["api_ip"])),
                        "storage_vm": str(rt.get("storage_vm", runtime["storage_vm"])),
                        "storage_iso": str(rt.get("storage_iso", runtime["storage_iso"])),
                        "storage_snippets": str(rt.get("storage_snippets", runtime["storage_snippets"])),
                        "bridge": str(rt.get("bridge", runtime["bridge"])),
                        "storage_vm_source": str(rt.get("storage_vm_source", runtime["storage_vm_source"])),
                        "storage_iso_source": str(rt.get("storage_iso_source", runtime["storage_iso_source"])),
                        "storage_snippets_source": str(rt.get("storage_snippets_source", runtime["storage_snippets_source"])),
                        "bridge_source": str(rt.get("bridge_source", runtime["bridge_source"])),
                    }
                )
                want_remote = False
        except FileNotFoundError:
            pass
        except Exception:
            pass

    if getattr(ns, "dry_run", False):
        print("dry-run: would run remote bootstrap and write outputs" if want_remote else "dry-run: would skip remote bootstrap")
        print("dry-run: would write credentials + readiness")
        print(f"run record: {evidence_dir}")
        return OK

    if want_remote:
        remote_dst = f"{ssh_username}@{values['host']}:{_REMOTE_BOOTSTRAP_DEST}"

        if getattr(ns, "remote_bootstrap", None):
            remote_script = Path(ns.remote_bootstrap).expanduser().resolve()
            if not remote_script.exists():
                print(f"remote bootstrap missing: {remote_script}")
                return INTERNAL_ERROR
            scp_res = run_capture(
                ["scp", "-q", *ssh_opts, str(remote_script), remote_dst],
                evidence_dir=evidence_dir,
                label="scp_upload",
                timeout_s=120,
                redact=True,
            )
        else:
            try:
                with _remote_script_path() as remote_script:
                    scp_res = run_capture(
                        ["scp", "-q", *ssh_opts, str(remote_script), remote_dst],
                        evidence_dir=evidence_dir,
                        label="scp_upload",
                        timeout_s=120,
                        redact=True,
                    )
            except Exception as e:
                print(f"remote bootstrap unavailable: {e}")
                return INTERNAL_ERROR

        if scp_res.rc != 0:
            print("scp upload failed; see evidence")
            return REMOTE_FAILED

        if bool(getattr(ns, "force", False)) and not has_vault_password:
            print("--force requires vault auth to persist rotated token secret")
            return SECRETS_FAILED

        env_parts = [
            f"USER_FQ={shlex.quote(values['user_fq'])}",
            f"TOKEN_NAME={shlex.quote(values['token_name'])}",
            f"FALLBACK_STORAGE_VM={shlex.quote(values['fallback_storage_vm'])}",
            f"FALLBACK_STORAGE_ISO={shlex.quote(values['fallback_storage_iso'])}",
            f"FALLBACK_STORAGE_SNIPPETS={shlex.quote(values['fallback_storage_snippets'])}",
            f"FALLBACK_BRIDGE={shlex.quote(values['fallback_bridge'])}",
        ]
        if token_secret and not bool(getattr(ns, "force", False)):
            env_parts.insert(0, "SKIP_TOKEN_GEN=1")

        ssh_cmd = [
            "ssh",
            *ssh_opts,
            f"{ssh_username}@{values['host']}",
            f'{" ".join(env_parts)} bash {_REMOTE_BOOTSTRAP_DEST}',
        ]
        ssh_res = run_capture_sensitive(
            ssh_cmd,
            evidence_dir=evidence_dir,
            label="remote_bootstrap",
            timeout_s=300,
        )

        if ssh_res.rc != 0:
            print("remote bootstrap failed; see evidence")
            return REMOTE_FAILED

        exports = _parse_exports((ssh_res.stdout or "") + "\n" + (ssh_res.stderr or ""))

        if (not token_secret) or bool(getattr(ns, "force", False)):
            new_secret = (exports.get("TOKEN_SECRET") or "").strip()
            if not new_secret:
                print("remote did not return TOKEN_SECRET")
                return REMOTE_FAILED
            token_secret = new_secret
            try:
                merge_set(vault_path, auth, {"PROXMOX_TOKEN_SECRET": token_secret})
            except Exception as e:
                print(f"vault write failed: {e}")
                return SECRETS_FAILED

        runtime["node"] = exports.get("NODE", runtime["node"])
        runtime["api_ip"] = exports.get("IP", runtime["api_ip"])
        runtime["storage_vm"] = exports.get("STORAGE_VM", runtime["storage_vm"])
        runtime["storage_iso"] = exports.get("STORAGE_ISO", runtime["storage_iso"])
        runtime["storage_snippets"] = exports.get("STORAGE_SNIPPETS", runtime["storage_snippets"])
        runtime["bridge"] = exports.get("BRIDGE", runtime["bridge"])
        runtime["storage_vm_source"] = exports.get("STORAGE_VM_SOURCE", runtime["storage_vm_source"])
        runtime["storage_iso_source"] = exports.get("STORAGE_ISO_SOURCE", runtime["storage_iso_source"])
        runtime["storage_snippets_source"] = exports.get("STORAGE_SNIPPETS_SOURCE", runtime["storage_snippets_source"])
        runtime["bridge_source"] = exports.get("BRIDGE_SOURCE", runtime["bridge_source"])

    if not token_secret:
        print("missing PROXMOX_TOKEN_SECRET; run init with vault auth")
        return SECRETS_FAILED

    if not _validate_api_token(
        evidence_dir=evidence_dir,
        api_ip=str(runtime.get("api_ip") or values["host"]),
        api_port=str(values.get("port") or "8006"),
        tls_skip=str(values.get("tls_skip") or "true"),
        token_id=token_id,
        token_secret=token_secret,
    ):
        print("proxmox token validation failed; check token/ACLs and API reachability")
        print(f"run record: {evidence_dir}")
        return SECRETS_FAILED

    if not _validate_storage_content_access(
        evidence_dir=evidence_dir,
        api_ip=str(runtime.get("api_ip") or values["host"]),
        api_port=str(values.get("port") or "8006"),
        tls_skip=str(values.get("tls_skip") or "true"),
        token_id=token_id,
        token_secret=token_secret,
        node=str(runtime.get("node") or ""),
        datastore=str(runtime.get("storage_snippets") or ""),
    ):
        print(
            "proxmox token validation failed for snippet storage content access; "
            "check token ACLs and storage_snippets discovery"
        )
        print(f"run record: {evidence_dir}")
        return SECRETS_FAILED

    rendered = _write_tfvars(cred_path, values, token_id, token_secret, runtime)
    if not str(rendered.get("ssh_public_key") or "").strip():
        print("warning: ssh_public_key is empty; packer builds may fail. Set proxmox.ssh_public_key or run ssh-keygen.")
        print(
            "hint: platform/onprem/vyos-edge with ssh_keys_from_init=true will fail until a key is present in proxmox.ready.json"
        )
    if not str(rendered.get("http_bind_address") or "").strip():
        print(
            "warning: http_bind_address is empty; packer builds may fail. "
            "Set proxmox.http_bind_address or pass --http-bind-address."
        )

    readiness = {
        "target": target,
        "status": "ready",
        "run_id": run_id,
        "paths": {
            "config": str(cfg_path),
            "vault": str(vault_path),
            "credentials": str(cred_path),
            "evidence_dir": str(evidence_dir),
        },
        "context": {
            "ssh_public_key": str(rendered.get("ssh_public_key") or "").strip(),
        },
        "runtime": {
            "node": runtime["node"],
            "api_ip": runtime["api_ip"],
            "storage_vm": runtime["storage_vm"],
            "storage_iso": runtime["storage_iso"],
            "storage_snippets": runtime["storage_snippets"],
            "bridge": runtime["bridge"],
            "storage_vm_source": runtime["storage_vm_source"],
            "storage_iso_source": runtime["storage_iso_source"],
            "storage_snippets_source": runtime["storage_snippets_source"],
            "bridge_source": runtime["bridge_source"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    marker = write_marker(paths.meta_dir, target, readiness)

    print(f"target={target} status=ready run_id={run_id}")
    print(f"run record: {evidence_dir}")
    print(f"readiness: {marker}")
    print(f"credentials: {cred_path}")
    print(
        "runtime discovery:"
        f" storage_vm={runtime['storage_vm']} ({runtime['storage_vm_source']}),"
        f" storage_iso={runtime['storage_iso']} ({runtime['storage_iso_source']}),"
        f" storage_snippets={runtime['storage_snippets']} ({runtime['storage_snippets_source']}),"
        f" bridge={runtime['bridge']} ({runtime['bridge_source']})"
    )
    return OK
