"""Repair-only retrieval of an authorised EVE-NG IOL licence.

The licence generator deliberately lives behind an operator-controlled broker.
Core only accepts a short-lived, signed iourc response for a host that previously
completed IOL setup and has since reported an exact host-binding mismatch.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from hyops.runtime.module_state import read_module_state
from hyops.runtime.vault import VaultAuth, read_env


SCHEMA = "hybridops/iol-license-repair/v1"
MODULE_REF = "platform/linux/eve-ng-images"
READY_OUTPUT = "eveng_images_iol_license_ready"
SECRET_KEY = "EVENG_IOL_LICENSE"
MAX_RESPONSE_BYTES = 64 * 1024

_MISMATCH = re.compile(
    r"IOL licence does not match this EVE-NG host\.\s*"
    r"Hostname:\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\.\s*"
    r"Host ID:\s*([0-9a-fA-F]{8})\.?",
    re.IGNORECASE,
)
_LICENCE_LINE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*=\s*([0-9a-fA-F]{16})\s*;\s*$"
)


class IolRepairError(RuntimeError):
    """A safe-to-display repair failure."""


@dataclass(frozen=True)
class IolMismatch:
    hostname: str
    host_id: str


@dataclass(frozen=True)
class IolRepairResult:
    request_id: str
    hostname: str
    host_id: str
    persisted_to: str


def parse_iol_mismatch(detail: str) -> IolMismatch | None:
    match = _MISMATCH.search(str(detail or ""))
    if not match:
        return None
    return IolMismatch(
        hostname=match.group(1).rstrip("."),
        host_id=match.group(2).rstrip("."),
    )


def _request_nonce() -> str:
    return base64.urlsafe_b64encode(os.urandom(24)).rstrip(b"=").decode("ascii")


def prior_success_allows_repair(state_dir: Path, state_ref: str) -> bool:
    """Require a previously published successful IOL readiness marker."""
    try:
        state = read_module_state(state_dir, state_ref)
    except Exception:
        return False
    outputs = state.get("outputs")
    return isinstance(outputs, dict) and outputs.get(READY_OUTPUT) is True


def _read_runtime_secrets(paths) -> dict[str, str]:
    vault_file = paths.vault_dir / "bootstrap.vault.env"
    try:
        return read_env(vault_file, VaultAuth())
    except Exception as exc:
        raise IolRepairError(f"could not read the runtime secret vault: {exc}") from exc


def _broker_url(ns) -> str:
    value = str(
        getattr(ns, "iol_repair_broker_url", None)
        or os.getenv("HYOPS_IOL_REPAIR_BROKER_URL")
        or ""
    ).strip()
    if not value:
        raise IolRepairError(
            "repair broker is not configured; set --iol-repair-broker-url or "
            "HYOPS_IOL_REPAIR_BROKER_URL"
        )
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise IolRepairError("repair broker URL must be an absolute https:// URL")
    return value


def _public_key_path(ns) -> Path:
    value = str(
        getattr(ns, "iol_repair_public_key", None)
        or os.getenv("HYOPS_IOL_REPAIR_PUBLIC_KEY")
        or ""
    ).strip()
    if not value:
        raise IolRepairError(
            "repair response key is not configured; set --iol-repair-public-key "
            "or HYOPS_IOL_REPAIR_PUBLIC_KEY"
        )
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise IolRepairError(f"repair response public key not found: {path}")
    return path


def _verify_response(body: bytes, signature_text: str, public_key_path: Path) -> None:
    if not signature_text:
        raise IolRepairError("repair broker response is missing its signature")
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        public_key.verify(signature, body)
    except InvalidSignature as exc:
        raise IolRepairError("repair broker response signature is invalid") from exc
    except IolRepairError:
        raise
    except Exception as exc:
        raise IolRepairError(f"could not verify repair broker response: {exc}") from exc


def _parse_expiry(value: Any) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise IolRepairError("repair broker response has no expiry")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IolRepairError("repair broker response has an invalid expiry") from exc
    if parsed.tzinfo is None:
        raise IolRepairError("repair broker response expiry must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_iourc(value: Any, hostname: str) -> str:
    content = str(value or "")
    if not content.strip() or len(content.encode("utf-8")) > 4096:
        raise IolRepairError("repair broker returned invalid licence material")
    lines = content.splitlines()
    if not lines or lines[0].strip().lower() != "[license]":
        raise IolRepairError("repair broker returned an invalid iourc document")
    bindings = [match for line in lines[1:] if (match := _LICENCE_LINE.match(line))]
    if len(bindings) != 1 or bindings[0].group(1).lower() != hostname.lower():
        raise IolRepairError("repair broker returned a licence for a different host")
    return f"[license]\n{hostname} = {bindings[0].group(2).lower()};\n"


def _persist_iourc(ns, paths, content: str) -> str:
    # Reuse the public secrets command so local encryption and optional external
    # authority persistence retain exactly the same semantics as operator writes.
    from hyops.secrets.command import run_set

    persist = str(getattr(ns, "iol_repair_persist", None) or "").strip() or None
    with tempfile.TemporaryDirectory(prefix="hyops-iol-repair-") as tmp:
        temp_dir = Path(tmp)
        os.chmod(temp_dir, 0o700)
        iourc_path = temp_dir / "iourc"
        iourc_path.write_text(content, encoding="utf-8")
        os.chmod(iourc_path, 0o600)
        secret_ns = argparse.Namespace(
            root=getattr(ns, "root", None),
            env=getattr(ns, "env", None),
            vault_file=None,
            vault_password_file=None,
            vault_password_command=None,
            persist=persist,
            persist_scope="all",
            persist_map_file=None,
            persist_register_gsm_map=(persist == "gsm"),
            persist_register_gsm_template="hyops-{env}-{scope}-{env_key_slug}",
            persist_project_id=None,
            persist_project_state_ref=None,
            from_env=[],
            from_file=[f"{SECRET_KEY}={iourc_path}"],
            pairs=[],
        )
        command_output = io.StringIO()
        with contextlib.redirect_stdout(command_output):
            rc = run_set(secret_ns)
        if rc != 0:
            raise IolRepairError("failed to store the repaired licence in the secret authority")
    return persist or "runtime-vault"


def repair_iol_license(ns, paths, *, state_ref: str, mismatch: IolMismatch) -> IolRepairResult:
    if not prior_success_allows_repair(paths.state_dir, state_ref):
        raise IolRepairError(
            "repair is allowed only after this image module previously published a "
            "successful IOL licence readiness marker"
        )

    runtime_secrets = _read_runtime_secrets(paths)
    existing = str(runtime_secrets.get(SECRET_KEY) or "")
    if not existing.strip():
        raise IolRepairError(
            "repair requires an existing EVENG_IOL_LICENSE in the runtime vault"
        )
    token_key = str(getattr(ns, "iol_repair_token_key", None) or "HYOPS_IOL_REPAIR_TOKEN")
    token = str(os.getenv(token_key) or runtime_secrets.get(token_key) or "").strip()
    if not token:
        raise IolRepairError(
            f"repair broker credential is missing; set {token_key} in the shell or runtime vault"
        )

    request_nonce = _request_nonce()
    request_body = {
        "schema": SCHEMA,
        "environment": str(getattr(ns, "env", None) or paths.root.name),
        "module_state_ref": state_ref,
        "hostname": mismatch.hostname,
        "host_id": mismatch.host_id,
        "previous_license_sha256": hashlib.sha256(existing.encode("utf-8")).hexdigest(),
        "previous_iol_ready": True,
        "nonce": request_nonce,
    }
    ca_bundle = str(os.getenv("HYOPS_IOL_REPAIR_CA_BUNDLE") or "").strip()
    try:
        response = requests.post(
            _broker_url(ns),
            json=request_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "hybridops-core-iol-repair/1",
            },
            timeout=(5, 25),
            verify=ca_bundle or True,
        )
    except requests.RequestException as exc:
        raise IolRepairError(f"repair broker request failed: {exc}") from exc
    if response.status_code != 200:
        raise IolRepairError(f"repair broker rejected the request (HTTP {response.status_code})")
    body = response.content
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise IolRepairError("repair broker returned an invalid response size")
    _verify_response(
        body,
        str(response.headers.get("X-HybridOps-Signature") or "").strip(),
        _public_key_path(ns),
    )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IolRepairError("repair broker returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise IolRepairError("repair broker returned an unsupported response schema")
    if str(payload.get("nonce") or "") != request_nonce:
        raise IolRepairError("repair broker response nonce does not match the request")
    if str(payload.get("hostname") or "").lower() != mismatch.hostname.lower():
        raise IolRepairError("repair broker response hostname does not match the request")
    if str(payload.get("host_id") or "").lower() != mismatch.host_id.lower():
        raise IolRepairError("repair broker response host ID does not match the request")
    now = datetime.now(timezone.utc)
    expires_at = _parse_expiry(payload.get("expires_at"))
    if expires_at <= now:
        raise IolRepairError("repair broker response has expired")
    if expires_at > now + timedelta(minutes=5):
        raise IolRepairError("repair broker response expiry exceeds five minutes")

    content = _validate_iourc(payload.get("iourc"), mismatch.hostname)
    persisted_to = _persist_iourc(ns, paths, content)
    return IolRepairResult(
        request_id=str(payload.get("request_id") or "").strip(),
        hostname=mismatch.hostname,
        host_id=mismatch.host_id,
        persisted_to=persisted_to,
    )
