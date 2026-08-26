"""Result parsing helpers for the Ansible config driver."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_IOL_HOST_MISMATCH = re.compile(
    r"does not contain a licence entry for (?:"
    r"this EVE-NG host\.\s+Hostname:\s*|the EVE-NG hostname\s+)"
    r"([A-Za-z0-9][A-Za-z0-9_.-]*)",
    re.IGNORECASE,
)
_IOL_HOST_IDENTIFIER = re.compile(
    r"Host ID:\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)",
    re.IGNORECASE,
)


def ansible_error_hint(
    *,
    command_name: str,
    module_ref: str,
    inputs: dict[str, Any],
    evidence_dir: Path,
    label: str,
) -> str:
    if command_name != "apply":
        return ""

    chunks: list[str] = []
    for name in (f"{label}.stdout.txt", f"{label}.stderr.txt"):
        path = (evidence_dir / name).resolve()
        if not path.exists():
            continue
        try:
            data = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if data:
            chunks.append(data[-20000:])
    tail = "\n".join(chunks)
    if not tail:
        return ""
    lowered_tail = tail.lower()

    if module_ref.strip().lower() in {
        "platform/linux/eve-ng-images",
        "platform/linux/gns3-images",
    } and (
        "reached your bandwidth quota" in lowered_tail
        or "mega transfer quota reached" in lowered_tail
    ):
        return (
            "MEGA transfer quota reached. Completed downloads remain cached. "
            "Retry after the quota resets or use another authorised source URL."
        )

    if (
        module_ref.strip().lower() == "platform/linux/eve-ng-images"
        and "supplied iol licence file is not a valid iourc document" in lowered_tail
    ):
        return (
            "IOL licence content is not a valid iourc document. "
            "Store an authorised iourc with hyops secrets set --from-file, then rerun. "
            "No images were changed."
        )

    iol_host_mismatch = _IOL_HOST_MISMATCH.search(tail)
    if module_ref.strip().lower() == "platform/linux/eve-ng-images" and iol_host_mismatch:
        hostname = iol_host_mismatch.group(1).rstrip(".")
        host_identifier_match = _IOL_HOST_IDENTIFIER.search(tail)
        host_identifier = (
            f" Host ID: {host_identifier_match.group(1).rstrip('.')}."
            if host_identifier_match
            else ""
        )
        return (
            "IOL licence does not match this EVE-NG host. "
            f"Hostname: {hostname}.{host_identifier} "
            "Update EVENG_IOL_LICENSE with an authorised iourc for this host, then rerun. "
            "No images were changed."
        )

    if "data directory" in lowered_tail and "already initialized" in lowered_tail:
        if module_ref.strip().lower() in {"platform/postgresql-ha", "platform/onprem/postgresql-ha"} and str(inputs.get("apply_mode") or "").strip().lower() in ("", "auto", "bootstrap"):
            return (
                "postgresql-ha bootstrap detected existing initialized data directories. "
                "This usually means a prior bootstrap partially completed. "
                "Re-run with `inputs.apply_mode=maintenance`, or run `hyops destroy` for this module and bootstrap again."
            )
        return (
            "remote PostgreSQL data directories are already initialized. "
            "Use the module maintenance path for in-place reconciliation, or clean hosts before bootstrap."
        )

    if (
        module_ref.strip().lower() == "platform/linux/eve-ng-lab-archive"
        and "qemu nodes are running" in lowered_tail
    ):
        return (
            "EVE-NG nodes are still running. Stop all active lab nodes in the "
            "EVE-NG UI, then repeat the archive operation. No resources were destroyed."
        )

    return ""


def load_outputs(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    return payload
