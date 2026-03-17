"""Connectivity and SSH preflight helpers for the Ansible config driver."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_bool, as_int
from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.module_state import split_module_state_ref
from hyops.runtime.proc import run_capture

_LABEL_SAFE_RE = re.compile(r"[^0-9A-Za-z_.-]+")
_EXECUTION_PLANES = {"workstation-direct", "runner-local"}
_SSH_ACCESS_MODES = {"direct", "bastion-explicit", "gcp-iap"}
_PLACEHOLDER_HOSTS = {"0.0.0.0"}


def expand_existing_file(raw: str) -> tuple[str, str]:
    token = str(raw or "").strip()
    if not token:
        return "", ""
    path = Path(token).expanduser()
    if not path.exists():
        return "", f"file not found: {path}"
    try:
        return str(path.resolve()), ""
    except Exception:
        return str(path), ""


def safe_label_token(raw: str) -> str:
    token = _LABEL_SAFE_RE.sub("_", str(raw or "").strip())
    token = token.strip("._-")
    return token or "host"


def is_placeholder_host(raw: Any) -> bool:
    token = str(raw or "").strip()
    return token in _PLACEHOLDER_HOSTS


def probe_tcp(host: str, port: int, timeout_s: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout_s)):
            return True, ""
    except Exception as exc:
        return False, str(exc)


def resolve_default_bastion(runtime_root: Path) -> tuple[str, str]:
    """Best-effort default bastion sourced from proxmox init metadata/credentials."""

    api_ip = ""
    ssh_user = ""
    try:
        proxmox_ready = (runtime_root / "meta" / "proxmox.ready.json").resolve()
        if not proxmox_ready.exists():
            return "", ""
        payload = json.loads(proxmox_ready.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return "", ""
        runtime = payload.get("runtime")
        if not isinstance(runtime, dict):
            return "", ""
        api_ip = str(runtime.get("api_ip") or "").strip()
    except Exception:
        api_ip = ""

    if not api_ip:
        return "", ""

    try:
        tfvars = parse_tfvars((runtime_root / "credentials" / "proxmox.credentials.tfvars").resolve())
        ssh_user = str(tfvars.get("proxmox_ssh_username") or "").strip()
    except Exception:
        ssh_user = ""

    return api_ip, ssh_user


def hint_default_bastion(runtime_root: Path) -> str:
    """Best-effort hint for operators when mgmt networks are unreachable from the workstation."""

    api_ip, _ = resolve_default_bastion(runtime_root)
    if not api_ip:
        return ""
    return f" Hint: proxmox init detected; try ssh_proxy_jump_host={api_ip}."


def execution_plane(inputs: dict[str, Any]) -> str:
    token = str(inputs.get("execution_plane") or "workstation-direct").strip().lower()
    if token not in _EXECUTION_PLANES:
        return "workstation-direct"
    return token


def ssh_access_mode(inputs: dict[str, Any]) -> str:
    token = str(inputs.get("ssh_access_mode") or "").strip().lower()
    if token == "gcp-iap":
        return token
    if str(inputs.get("ssh_proxy_jump_host") or "").strip():
        return "bastion-explicit"
    if token in _SSH_ACCESS_MODES:
        return token
    return "direct"


def _classify_ssh_auth_probe_failure(
    *,
    result: Any,
    label: str,
    access_mode: str,
    gcp_iap_instance: str,
    gcp_iap_project_id: str,
    gcp_iap_zone: str,
) -> str:
    stderr = str(getattr(result, "stderr", "") or "")
    stdout = str(getattr(result, "stdout", "") or "")
    combined = f"{stdout}\n{stderr}".lower()

    if access_mode == "gcp-iap" and "not authorized" in combined and "iap" in combined:
        return (
            "gcp-iap tunnel authorisation failed for "
            f"instance={gcp_iap_instance} project={gcp_iap_project_id} zone={gcp_iap_zone}. "
            "Confirm the active gcloud identity has IAP-secured Tunnel User access and OS/Login or SSH access "
            f"for the target. See {label}.* in evidence dir."
        )

    if "banner exchange" in combined or "connection timed out" in combined:
        return f"ssh service did not become ready yet (see {label}.* in evidence dir)"

    if "permission denied" in combined or "publickey" in combined or "authentication failed" in combined:
        return f"ssh authentication failed (see {label}.* in evidence dir)"

    return f"ssh auth probe failed (see {label}.* in evidence dir)"


def unreachable_access_hint(
    *,
    inputs: dict[str, Any],
    runtime_root: Path,
    target_label: str,
    host: str,
    port: int,
    timeout_s: int,
    err: str,
) -> str:
    plane = execution_plane(inputs)
    access_mode_token = ssh_access_mode(inputs)
    bastion_hint = hint_default_bastion(runtime_root) if _auto_proxy_allowed(inputs) else ""
    if access_mode_token == "gcp-iap":
        return (
            "connectivity check failed: GCP IAP access could not establish SSH reachability for "
            f"{target_label} host={host}:{port}. Ensure gcloud is installed, authenticated, "
            "IAP TCP forwarding is allowed, and the target metadata includes the expected SSH key."
        )
    if plane == "runner-local":
        return (
            "connectivity check failed: cannot reach "
            f"{target_label} host={host}:{port} from this execution host (timeout={timeout_s}s): {err}. "
            "Execute this run from a shared runner with L3 access to the target network, "
            "or configure inputs.ssh_proxy_jump_host for an explicit bastion."
        )
    return (
        "connectivity check failed: cannot reach "
        f"{target_label} host={host}:{port} from this machine (timeout={timeout_s}s): {err}. "
        "Ensure your workstation has L3 access to the management network (VPN/route), "
        "or configure inputs.ssh_proxy_jump_host for a bastion."
        + bastion_hint
    )


def _state_ref_base(raw_ref: Any) -> str:
    token = str(raw_ref or "").strip()
    if not token:
        return ""
    try:
        base, _instance = split_module_state_ref(token)
    except Exception:
        return ""
    return str(base or "").strip().lower()


def _is_cloud_state_ref(base_ref: str) -> bool:
    token = str(base_ref or "").strip().lower()
    if not token:
        return False
    return any(seg in token.split("/") for seg in ("gcp", "aws", "azure", "hetzner"))


def _auto_proxy_allowed(inputs: dict[str, Any]) -> bool:
    """Limit proxmox-derived auto-bastion to on-prem targets only.

    Cloud restore/failover inventories often publish private cloud IPs. Reusing
    a Proxmox bastion automatically for those targets is misleading unless the
    operator has separately established WAN/VPN reachability.
    """

    inventory_base = _state_ref_base(inputs.get("inventory_state_ref"))
    target_base = _state_ref_base(inputs.get("target_state_ref"))
    managed_target_base = _state_ref_base(inputs.get("managed_target_state_ref"))

    for base_ref in (inventory_base, target_base, managed_target_base):
        if _is_cloud_state_ref(base_ref):
            return False
    return True


def apply_proxy_jump_auto(inputs: dict[str, Any], runtime_root: Path) -> str:
    """Auto-fill proxy jump host from proxmox init when enabled and unset."""

    if str(inputs.get("ssh_proxy_jump_host") or "").strip():
        return ""
    if not as_bool(inputs.get("ssh_proxy_jump_auto"), default=False):
        return ""
    if not _auto_proxy_allowed(inputs):
        return ""

    proxy_host, detected_user = resolve_default_bastion(runtime_root)
    if not proxy_host:
        return ""

    inputs["ssh_proxy_jump_host"] = proxy_host

    current_user = str(inputs.get("ssh_proxy_jump_user") or "").strip()
    if not current_user and detected_user:
        inputs["ssh_proxy_jump_user"] = detected_user

    effective_user = str(inputs.get("ssh_proxy_jump_user") or "").strip() or "root"
    return f"auto-enabled ssh proxy jump via {effective_user}@{proxy_host} from proxmox init metadata"


def probe_proxy_target_port(
    *,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
    ssh_private_key_file: str,
    target_host: str,
    target_port: int,
    timeout_s: int,
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    redact: bool,
    label: str,
) -> tuple[bool, str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return False, "missing command: ssh"

    argv = [
        ssh_bin,
        "-p",
        str(proxy_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    if ssh_private_key_file:
        argv.extend(["-i", ssh_private_key_file])

    argv.extend(
        [
            f"{proxy_user}@{proxy_host}",
            "nc",
            "-vz",
            "-w",
            str(max(1, int(timeout_s))),
            target_host,
            str(int(target_port)),
        ]
    )

    try:
        r = run_capture(
            argv,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            label=label,
            timeout_s=max(5, int(timeout_s) + 5),
            redact=redact,
        )
    except subprocess.TimeoutExpired:
        return False, f"proxy port test timed out after {max(5, int(timeout_s) + 5)}s"
    except Exception as exc:
        return False, f"proxy port test failed: {exc}"
    if r.rc == 0:
        return True, ""
    return False, f"proxy port test failed (see {label}.* in evidence dir)"


def probe_ssh_auth(
    *,
    target_host: str,
    target_user: str,
    target_port: int,
    ssh_private_key_file: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
    timeout_s: int,
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    redact: bool,
    label: str,
    access_mode: str = "direct",
    gcp_iap_instance: str = "",
    gcp_iap_project_id: str = "",
    gcp_iap_zone: str = "",
) -> tuple[bool, str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return False, "missing command: ssh"

    connect_timeout_s = max(1, int(timeout_s))
    if access_mode == "gcp-iap":
        connect_timeout_s = max(10, connect_timeout_s)

    argv = [
        ssh_bin,
        "-p",
        str(int(target_port)),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout_s}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]

    if access_mode == "gcp-iap":
        gcloud_bin = shutil.which("gcloud")
        if not gcloud_bin:
            return False, "missing command: gcloud"
        if not gcp_iap_instance or not gcp_iap_project_id or not gcp_iap_zone:
            return False, "gcp-iap requires instance, project_id, and zone"
        proxy_cmd = (
            f"{gcloud_bin} compute start-iap-tunnel {shlex.quote(gcp_iap_instance)} %p "
            f"--listen-on-stdin --project {shlex.quote(gcp_iap_project_id)} "
            f"--zone {shlex.quote(gcp_iap_zone)} --verbosity=warning"
        )
        argv.extend(["-o", f"ProxyCommand={proxy_cmd}"])
    elif proxy_host:
        proxy_cmd_parts = [
            "ssh",
            "-p",
            str(int(proxy_port)),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
        if ssh_private_key_file:
            proxy_cmd_parts.extend(["-i", ssh_private_key_file])
        proxy_cmd_parts.append(f"{proxy_user}@{proxy_host}")
        proxy_cmd_parts.extend(["nc", "%h", "%p"])
        proxy_cmd = " ".join(proxy_cmd_parts)
        argv.extend(["-o", f"ProxyCommand={proxy_cmd}"])

    if ssh_private_key_file:
        argv.extend(["-i", ssh_private_key_file])

    argv.extend([f"{target_user}@{target_host}", "true"])

    attempts = 3 if access_mode == "gcp-iap" else 1
    delay_s = 2
    last_err = ""
    for attempt in range(1, attempts + 1):
        try:
            r = run_capture(
                argv,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                label=label,
                timeout_s=max(5, connect_timeout_s + 5),
                redact=redact,
            )
        except subprocess.TimeoutExpired:
            last_err = f"ssh auth probe timed out after {max(5, connect_timeout_s + 5)}s"
        except Exception as exc:
            last_err = f"ssh auth probe failed: {exc}"
        else:
            if r.rc == 0:
                return True, ""
            last_err = _classify_ssh_auth_probe_failure(
                result=r,
                label=label,
                access_mode=access_mode,
                gcp_iap_instance=gcp_iap_instance,
                gcp_iap_project_id=gcp_iap_project_id,
                gcp_iap_zone=gcp_iap_zone,
            )

        if access_mode != "gcp-iap":
            break
        retryable = (
            "ssh service did not become ready yet" in last_err
            or "ssh auth probe timed out" in last_err
        )
        if not retryable:
            break
        if attempt < attempts:
            time.sleep(delay_s)

    return False, last_err


def pick_rke2_probe_target(inputs: dict[str, Any]) -> tuple[str, str]:
    groups = inputs.get("inventory_groups")
    if isinstance(groups, dict):
        servers = groups.get("rke2_servers")
        if isinstance(servers, list):
            for item in servers:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                host = str(item.get("host") or item.get("ansible_host") or "").strip()
                if host:
                    return name or host, host

        # Fallback: first host from any group.
        for _, members in groups.items():
            if not isinstance(members, list):
                continue
            for item in members:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                host = str(item.get("host") or item.get("ansible_host") or "").strip()
                if host:
                    return name or host, host

    target_host = str(inputs.get("target_host") or "").strip()
    if target_host:
        return target_host, target_host
    return "", ""


def rke2_image_preflight_check(
    *,
    command_name: str,
    module_ref: str,
    inputs: dict[str, Any],
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    redact: bool,
) -> tuple[bool, str]:
    if command_name not in ("apply", "preflight", "plan"):
        return True, ""
    if str(module_ref or "").strip().lower() != "platform/onprem/rke2-cluster":
        return True, ""
    if not as_bool(inputs.get("rke2_image_preflight"), default=True):
        return True, ""

    role_vars = inputs.get("rke2_role_vars")
    if not isinstance(role_vars, dict):
        role_vars = {}
    install_version = str(role_vars.get("install_rke2_version") or "").strip()
    if not install_version:
        return True, ""

    # If image tarballs are configured (explicit, role-level, or auto mode),
    # skip remote registry tag probing. Bootstrap will import image tarballs.
    explicit_tar_urls = inputs.get("rke2_image_tarball_urls")
    has_explicit_tar_urls = isinstance(explicit_tar_urls, list) and any(str(x).strip() for x in explicit_tar_urls)
    role_tar_urls = role_vars.get("rke2_images_urls")
    has_role_tar_urls = isinstance(role_tar_urls, list) and any(str(x).strip() for x in role_tar_urls)
    auto_tarballs = as_bool(inputs.get("rke2_auto_image_tarballs"), default=False)
    if has_explicit_tar_urls or has_role_tar_urls or (auto_tarballs and install_version):
        return True, ""

    target_label, target_host = pick_rke2_probe_target(inputs)
    if not target_host:
        return False, "rke2 image preflight failed: no inventory target available for probe"

    target_user = str(inputs.get("target_user") or "").strip() or "root"
    target_port = as_int(inputs.get("target_port"), default=22)
    timeout_s = max(30, as_int(inputs.get("rke2_image_preflight_timeout_s"), default=180))

    ssh_private_key_file, key_err = expand_existing_file(str(inputs.get("ssh_private_key_file") or ""))
    if key_err:
        return False, f"rke2 image preflight failed: inputs.ssh_private_key_file {key_err}"

    proxy_host = str(inputs.get("ssh_proxy_jump_host") or "").strip()
    proxy_user = str(inputs.get("ssh_proxy_jump_user") or "").strip() or "root"
    proxy_port = as_int(inputs.get("ssh_proxy_jump_port"), default=22)

    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return False, "rke2 image preflight failed: missing command: ssh"

    remote_script = r"""
set -euo pipefail
RKE2_VERSION="${RKE2_VERSION:-}"
if [ -z "$RKE2_VERSION" ]; then
  echo '{"error":"install_rke2_version is required for image preflight"}'
  exit 10
fi

RKE2_VERSION="${RKE2_VERSION#v}"
RUNTIME_TAG="v${RKE2_VERSION/+/-}"

tmpd="$(mktemp -d)"
cleanup() { rm -rf "$tmpd"; }
trap cleanup EXIT

refs_file="$tmpd/rke2-image-refs.txt"

# Preferred source: live image lists generated by installed RKE2 package/service.
if sudo test -d /var/lib/rancher/rke2/agent/images >/dev/null 2>&1; then
  sudo find /var/lib/rancher/rke2/agent/images -maxdepth 1 -type f -name '*.txt' -print0 \
    | xargs -0 -r sudo cat \
    | sed '/^[[:space:]]*$/d;/^[[:space:]]*#/d' \
    | sort -u > "$refs_file" || true
fi

# Fallback for fresh hosts: at least validate the runtime image tag for chosen version.
if [ ! -s "$refs_file" ]; then
  echo "index.docker.io/rancher/rke2-runtime:${RUNTIME_TAG}" > "$refs_file"
fi

python3 - "$refs_file" <<'PY'
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

refs_path = pathlib.Path(sys.argv[1])
refs = []
for raw in refs_path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    refs.append(line)
refs = sorted(set(refs))
if not refs:
    print(json.dumps({"error": "no image refs available on target host"}))
    sys.exit(13)

def split_ref(ref: str):
    ref = ref.split("@", 1)[0]
    if ":" not in ref.rsplit("/", 1)[-1]:
        return "", "", ""
    path, tag = ref.rsplit(":", 1)
    if "/" not in path:
        return "docker.io", f"library/{path}", tag
    first, rest = path.split("/", 1)
    if "." in first or ":" in first or first == "localhost":
        return first, rest, tag
    return "docker.io", path, tag

def check_docker_hub(repo: str, tag: str, timeout: int = 10):
    token_url = (
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:"
        + urllib.parse.quote(repo, safe="/")
        + ":pull"
    )
    with urllib.request.urlopen(token_url, timeout=timeout) as r:
        token = json.loads(r.read().decode("utf-8")).get("token", "")
    if not token:
        return False, "auth_token_missing"

    req = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}",
        headers={
            "Accept": (
                "application/vnd.docker.distribution.manifest.v2+json,"
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.oci.image.index.v1+json"
            ),
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True, ""
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:  # pragma: no cover - best effort runtime probe
        return False, str(exc)

missing = []
checked = 0
for ref in refs:
    registry, repo, tag = split_ref(ref)
    if not registry or not repo or not tag:
        continue
    checked += 1
    ok = False
    err = ""
    try:
        if registry in ("docker.io", "index.docker.io", "registry-1.docker.io"):
            ok, err = check_docker_hub(repo, tag)
        else:
            req = urllib.request.Request(f"https://{registry}/v2/{repo}/manifests/{tag}")
            with urllib.request.urlopen(req, timeout=10):
                ok = True
    except urllib.error.HTTPError as exc:
        err = f"http_{exc.code}"
    except Exception as exc:  # pragma: no cover
        err = str(exc)
    if not ok:
        missing.append({"ref": ref, "error": err})

summary = {
    "checked": checked,
    "missing_count": len(missing),
    "missing": missing[:20],
}
print(json.dumps(summary))
sys.exit(0 if not missing else 42)
PY
"""

    argv = [
        ssh_bin,
        "-p",
        str(int(target_port)),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(5, min(30, int(timeout_s)))}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    if proxy_host:
        proxy_cmd_parts = [
            "ssh",
            "-p",
            str(int(proxy_port)),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
        if ssh_private_key_file:
            proxy_cmd_parts.extend(["-i", ssh_private_key_file])
        proxy_cmd_parts.append(f"{proxy_user}@{proxy_host}")
        proxy_cmd_parts.extend(["nc", "%h", "%p"])
        proxy_cmd = " ".join(proxy_cmd_parts)
        argv.extend(["-o", f"ProxyCommand={proxy_cmd}"])
    if ssh_private_key_file:
        argv.extend(["-i", ssh_private_key_file])

    quoted_script = shlex.quote(remote_script)
    remote_cmd = f"RKE2_VERSION={shlex.quote(install_version)} /bin/bash -lc {quoted_script}"
    argv.extend([f"{target_user}@{target_host}", remote_cmd])

    label = f"rke2_image_preflight.{safe_label_token(target_label)}"
    try:
        r = run_capture(
            argv,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            label=label,
            timeout_s=timeout_s,
            redact=redact,
        )
    except subprocess.TimeoutExpired:
        return False, f"rke2 image preflight failed: probe timed out after {timeout_s}s"
    except Exception as exc:
        return False, f"rke2 image preflight failed: probe execution error: {exc}"

    stdout = (r.stdout or "").strip()
    stderr = (r.stderr or "").strip()
    if r.rc == 0:
        return True, ""

    if r.rc == 42:
        detail = stdout or stderr or "missing remote image tags"
        return False, (
            "rke2 image preflight failed: one or more image tags required by selected RKE2 package are unavailable. "
            f"details={detail} (see {label}.* in evidence dir)"
        )

    detail = stdout or stderr or f"probe exited rc={r.rc}"
    return False, f"rke2 image preflight failed: {detail} (see {label}.* in evidence dir)"


def connectivity_check(
    *,
    command_name: str,
    inputs: dict[str, Any],
    runtime_root: Path,
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    redact: bool,
) -> tuple[bool, str]:
    if command_name not in ("apply", "plan", "destroy", "preflight"):
        return True, ""

    if not as_bool(inputs.get("connectivity_check"), default=True):
        return True, ""

    inventory_groups = inputs.get("inventory_groups")
    if isinstance(inventory_groups, dict) and inventory_groups:
        targets: list[tuple[str, str]] = []
        seen_hosts: set[str] = set()
        for raw_group, raw_hosts in inventory_groups.items():
            group = str(raw_group or "").strip() or "group"
            if not isinstance(raw_hosts, list):
                continue
            for item in raw_hosts:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                host = str(item.get("host") or item.get("ansible_host") or "").strip()
                if not host:
                    continue
                if is_placeholder_host(host):
                    continue
                if host in seen_hosts:
                    continue
                seen_hosts.add(host)
                label = safe_label_token(f"{group}.{name or host}")
                targets.append((label, host))

        if not targets:
            placeholder_present = any(
                isinstance(item, dict)
                and is_placeholder_host(item.get("host") or item.get("ansible_host"))
                for members in inventory_groups.values()
                if isinstance(members, list)
                for item in members
            )
            if placeholder_present:
                return True, ""
            return False, "connectivity check failed: inputs.inventory_groups contains no usable hosts"

        target_user = str(inputs.get("target_user") or "").strip() or "root"
        target_port = as_int(inputs.get("target_port"), default=22)
        timeout_s = max(1, as_int(inputs.get("connectivity_timeout_s"), default=5))
        wait_s = max(0, as_int(inputs.get("connectivity_wait_s"), default=0))
        deadline = time.time() + float(wait_s)

        ssh_private_key_file, key_err = expand_existing_file(str(inputs.get("ssh_private_key_file") or ""))
        if key_err:
            return False, f"connectivity check failed: inputs.ssh_private_key_file {key_err}"

        proxy_host = str(inputs.get("ssh_proxy_jump_host") or "").strip()
        proxy_user = str(inputs.get("ssh_proxy_jump_user") or "").strip() or "root"
        proxy_port = as_int(inputs.get("ssh_proxy_jump_port"), default=22)

        if not proxy_host:
            for label, host in targets:
                if ssh_access_mode(inputs) == "direct":
                    ok, err = probe_tcp(host, target_port, timeout_s)
                    while not ok and time.time() < deadline:
                        time.sleep(3)
                        ok, err = probe_tcp(host, target_port, timeout_s)
                    if not ok:
                        hint = unreachable_access_hint(
                            inputs=inputs,
                            runtime_root=runtime_root,
                            target_label=label,
                            host=host,
                            port=target_port,
                            timeout_s=timeout_s,
                            err=err,
                        )
                        return False, hint

                access_mode = ssh_access_mode(inputs)
                gcp_iap_instance = ""
                gcp_iap_project_id = ""
                gcp_iap_zone = ""
                if access_mode == "gcp-iap":
                    group = next((members for members in inventory_groups.values() if isinstance(members, list) and any(isinstance(item, dict) and str(item.get("host") or item.get("ansible_host") or "").strip() == host for item in members)), [])
                    match_item = next((item for item in group if isinstance(item, dict) and str(item.get("host") or item.get("ansible_host") or "").strip() == host), {})
                    gcp_iap_instance = str(match_item.get("gcp_iap_instance") or "").strip()
                    gcp_iap_project_id = str(match_item.get("gcp_iap_project_id") or inputs.get("gcp_iap_project_id") or "").strip()
                    gcp_iap_zone = str(match_item.get("gcp_iap_zone") or inputs.get("gcp_iap_zone") or "").strip()
                ok, err = probe_ssh_auth(
                    target_host=host,
                    target_user=target_user,
                    target_port=target_port,
                    ssh_private_key_file=ssh_private_key_file,
                    proxy_host="",
                    proxy_user="",
                    proxy_port=0,
                    timeout_s=timeout_s,
                    cwd=cwd,
                    env=env,
                    evidence_dir=evidence_dir,
                    redact=redact,
                    label=f"connectivity_ssh_auth.{label}",
                    access_mode=access_mode,
                    gcp_iap_instance=gcp_iap_instance,
                    gcp_iap_project_id=gcp_iap_project_id,
                    gcp_iap_zone=gcp_iap_zone,
                )
                attempt = 1
                while not ok and time.time() < deadline:
                    attempt += 1
                    time.sleep(3)
                    ok, err = probe_ssh_auth(
                        target_host=host,
                        target_user=target_user,
                        target_port=target_port,
                        ssh_private_key_file=ssh_private_key_file,
                        proxy_host="",
                        proxy_user="",
                        proxy_port=0,
                        timeout_s=timeout_s,
                        cwd=cwd,
                        env=env,
                        evidence_dir=evidence_dir,
                        redact=redact,
                        label=f"connectivity_ssh_auth.{label}.try{attempt}",
                        access_mode=access_mode,
                        gcp_iap_instance=gcp_iap_instance,
                        gcp_iap_project_id=gcp_iap_project_id,
                        gcp_iap_zone=gcp_iap_zone,
                    )
                if not ok:
                    if err.startswith("gcp-iap tunnel authorisation failed"):
                        return False, f"connectivity check failed: {err}"
                    if err.startswith("ssh service did not become ready yet"):
                        return False, (
                            "connectivity check failed: target VM is reachable through its transport path, "
                            f"but SSH is not ready yet for {label} (host={host}). {err}"
                        )
                    hint = (
                        "connectivity check failed: target SSH port is reachable, but authentication failed for "
                        f"{label} (host={host}). Confirm target_user={target_user} exists and the SSH key is authorised. "
                        f"{err}"
                    )
                    return False, hint
            return True, ""

        ok, err = probe_tcp(proxy_host, proxy_port, timeout_s)
        while not ok and time.time() < deadline:
            time.sleep(3)
            ok, err = probe_tcp(proxy_host, proxy_port, timeout_s)
        if not ok:
            return False, (
                f"connectivity check failed: cannot reach ssh_proxy_jump_host={proxy_host}:{proxy_port} "
                f"(timeout={timeout_s}s): {err}"
            )

        for label, host in targets:
            ok, err = probe_proxy_target_port(
                proxy_host=proxy_host,
                proxy_user=proxy_user,
                proxy_port=proxy_port,
                ssh_private_key_file=ssh_private_key_file,
                target_host=host,
                target_port=target_port,
                timeout_s=timeout_s,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                redact=redact,
                label=f"connectivity_proxy_nc.{label}",
            )
            attempt = 1
            while not ok and time.time() < deadline:
                attempt += 1
                time.sleep(3)
                ok, err = probe_proxy_target_port(
                    proxy_host=proxy_host,
                    proxy_user=proxy_user,
                    proxy_port=proxy_port,
                    ssh_private_key_file=ssh_private_key_file,
                    target_host=host,
                    target_port=target_port,
                    timeout_s=timeout_s,
                    cwd=cwd,
                    env=env,
                    evidence_dir=evidence_dir,
                    redact=redact,
                    label=f"connectivity_proxy_nc.{label}.try{attempt}",
                )
            if not ok:
                return False, (
                    "connectivity check failed: proxy is reachable, but cannot reach the target from the proxy "
                    f"({proxy_user}@{proxy_host} -> {host}:{target_port}) for {label}. {err}"
                )

            ok, err = probe_ssh_auth(
                target_host=host,
                target_user=target_user,
                target_port=target_port,
                ssh_private_key_file=ssh_private_key_file,
                proxy_host=proxy_host,
                proxy_user=proxy_user,
                proxy_port=proxy_port,
                timeout_s=timeout_s,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                redact=redact,
                label=f"connectivity_ssh_auth.{label}",
            )
            attempt = 1
            while not ok and time.time() < deadline:
                attempt += 1
                time.sleep(3)
                ok, err = probe_ssh_auth(
                    target_host=host,
                    target_user=target_user,
                    target_port=target_port,
                    ssh_private_key_file=ssh_private_key_file,
                    proxy_host=proxy_host,
                    proxy_user=proxy_user,
                    proxy_port=proxy_port,
                    timeout_s=timeout_s,
                    cwd=cwd,
                    env=env,
                    evidence_dir=evidence_dir,
                    redact=redact,
                    label=f"connectivity_ssh_auth.{label}.try{attempt}",
                )
            if not ok:
                return False, (
                    "connectivity check failed: target is reachable via proxy, but SSH authentication failed for "
                    f"{label} (host={host}). Confirm target_user={target_user} and key injection. {err}"
                )

        return True, ""

    target_host = str(inputs.get("target_host") or "").strip()
    target_user = str(inputs.get("target_user") or "").strip() or "root"
    target_port = as_int(inputs.get("target_port"), default=22)
    if not target_host:
        return True, ""
    if is_placeholder_host(target_host):
        return True, ""

    timeout_s = max(1, as_int(inputs.get("connectivity_timeout_s"), default=5))
    wait_s = max(0, as_int(inputs.get("connectivity_wait_s"), default=0))
    deadline = time.time() + float(wait_s)

    ssh_private_key_file, key_err = expand_existing_file(str(inputs.get("ssh_private_key_file") or ""))
    if key_err:
        return False, f"connectivity check failed: inputs.ssh_private_key_file {key_err}"

    proxy_host = str(inputs.get("ssh_proxy_jump_host") or "").strip()
    proxy_user = str(inputs.get("ssh_proxy_jump_user") or "").strip() or "root"
    proxy_port = as_int(inputs.get("ssh_proxy_jump_port"), default=22)
    access_mode = ssh_access_mode(inputs)

    # Direct connectivity when no proxy is provided.
    if access_mode == "direct":
        ok, err = probe_tcp(target_host, target_port, timeout_s)
        while not ok and time.time() < deadline:
            time.sleep(3)
            ok, err = probe_tcp(target_host, target_port, timeout_s)
        if not ok:
            hint = unreachable_access_hint(
                inputs=inputs,
                runtime_root=runtime_root,
                target_label="target_host",
                host=target_host,
                port=target_port,
                timeout_s=timeout_s,
                err=err,
            )
            return False, hint

        ok, err = probe_ssh_auth(
            target_host=target_host,
            target_user=target_user,
            target_port=target_port,
            ssh_private_key_file=ssh_private_key_file,
            proxy_host="",
            proxy_user="",
            proxy_port=0,
            timeout_s=timeout_s,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            redact=redact,
            label="connectivity_ssh_auth",
            access_mode="direct",
        )
        attempt = 1
        while not ok and time.time() < deadline:
            attempt += 1
            time.sleep(3)
            ok, err = probe_ssh_auth(
                target_host=target_host,
                target_user=target_user,
                target_port=target_port,
                ssh_private_key_file=ssh_private_key_file,
                proxy_host="",
                proxy_user="",
                proxy_port=0,
                timeout_s=timeout_s,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                redact=redact,
                label=f"connectivity_ssh_auth.try{attempt}",
                access_mode="direct",
            )
        if not ok:
            if err.startswith("gcp-iap tunnel authorisation failed"):
                return False, f"connectivity check failed: {err}"
            if err.startswith("ssh service did not become ready yet"):
                return False, f"connectivity check failed: target VM is reachable through its transport path, but SSH is not ready yet. {err}"
            hint = (
                "connectivity check failed: target SSH port is reachable, but authentication failed. "
                f"Confirm target_user={target_user} exists and the SSH key is authorised. {err}"
            )
            return False, hint
        return True, ""

    if access_mode == "gcp-iap":
        gcp_iap_instance = str(inputs.get("gcp_iap_instance") or "").strip()
        gcp_iap_project_id = str(inputs.get("gcp_iap_project_id") or "").strip()
        gcp_iap_zone = str(inputs.get("gcp_iap_zone") or "").strip()
        ok, err = probe_ssh_auth(
            target_host=target_host,
            target_user=target_user,
            target_port=target_port,
            ssh_private_key_file=ssh_private_key_file,
            proxy_host="",
            proxy_user="",
            proxy_port=0,
            timeout_s=timeout_s,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            redact=redact,
            label="connectivity_ssh_auth",
            access_mode="gcp-iap",
            gcp_iap_instance=gcp_iap_instance,
            gcp_iap_project_id=gcp_iap_project_id,
            gcp_iap_zone=gcp_iap_zone,
        )
        attempt = 1
        while not ok and time.time() < deadline:
            attempt += 1
            time.sleep(3)
            ok, err = probe_ssh_auth(
                target_host=target_host,
                target_user=target_user,
                target_port=target_port,
                ssh_private_key_file=ssh_private_key_file,
                proxy_host="",
                proxy_user="",
                proxy_port=0,
                timeout_s=timeout_s,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                redact=redact,
                label=f"connectivity_ssh_auth.try{attempt}",
                access_mode="gcp-iap",
                gcp_iap_instance=gcp_iap_instance,
                gcp_iap_project_id=gcp_iap_project_id,
                gcp_iap_zone=gcp_iap_zone,
            )
        if not ok:
            return False, unreachable_access_hint(
                inputs=inputs,
                runtime_root=runtime_root,
                target_label="target_host",
                host=target_host,
                port=target_port,
                timeout_s=timeout_s,
                err=err,
            )
        return True, ""

    # Proxy-based check: validate proxy reachability, then target reachability from proxy, then auth via proxy.
    ok, err = probe_tcp(proxy_host, proxy_port, timeout_s)
    while not ok and time.time() < deadline:
        time.sleep(3)
        ok, err = probe_tcp(proxy_host, proxy_port, timeout_s)
    if not ok:
        return False, (
            f"connectivity check failed: cannot reach ssh_proxy_jump_host={proxy_host}:{proxy_port} "
            f"(timeout={timeout_s}s): {err}"
        )

    ok, err = probe_proxy_target_port(
        proxy_host=proxy_host,
        proxy_user=proxy_user,
        proxy_port=proxy_port,
        ssh_private_key_file=ssh_private_key_file,
        target_host=target_host,
        target_port=target_port,
        timeout_s=timeout_s,
        cwd=cwd,
        env=env,
        evidence_dir=evidence_dir,
        redact=redact,
        label="connectivity_proxy_nc",
    )
    attempt = 1
    while not ok and time.time() < deadline:
        attempt += 1
        time.sleep(3)
        ok, err = probe_proxy_target_port(
            proxy_host=proxy_host,
            proxy_user=proxy_user,
            proxy_port=proxy_port,
            ssh_private_key_file=ssh_private_key_file,
            target_host=target_host,
            target_port=target_port,
            timeout_s=timeout_s,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            redact=redact,
            label=f"connectivity_proxy_nc.try{attempt}",
        )
    if not ok:
        return False, (
            "connectivity check failed: proxy is reachable, but cannot reach the target from the proxy "
            f"({proxy_user}@{proxy_host} -> {target_host}:{target_port}). {err}"
        )

    ok, err = probe_ssh_auth(
        target_host=target_host,
        target_user=target_user,
        target_port=target_port,
        ssh_private_key_file=ssh_private_key_file,
        proxy_host=proxy_host,
        proxy_user=proxy_user,
        proxy_port=proxy_port,
        timeout_s=timeout_s,
        cwd=cwd,
        env=env,
        evidence_dir=evidence_dir,
        redact=redact,
        label="connectivity_ssh_auth",
    )
    attempt = 1
    while not ok and time.time() < deadline:
        attempt += 1
        time.sleep(3)
        ok, err = probe_ssh_auth(
            target_host=target_host,
            target_user=target_user,
            target_port=target_port,
            ssh_private_key_file=ssh_private_key_file,
            proxy_host=proxy_host,
            proxy_user=proxy_user,
            proxy_port=proxy_port,
            timeout_s=timeout_s,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            redact=redact,
            label=f"connectivity_ssh_auth.try{attempt}",
        )
    if not ok:
        return False, (
            "connectivity check failed: target is reachable via proxy, but SSH authentication failed. "
            f"Confirm target_user={target_user} and key injection. {err}"
        )

    return True, ""
