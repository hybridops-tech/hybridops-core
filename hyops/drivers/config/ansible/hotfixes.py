"""Best-effort Ansible collection hotfixes for known upstream issues."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.runtime.evidence import EvidenceWriter


def _iter_ansible_collection_dirs(env: dict[str, str]) -> list[Path]:
    """Return ansible_collections search roots from ANSIBLE_COLLECTIONS_PATH.

    Operates on the resolved directory list instead of invoking
    `ansible-galaxy` so the driver can apply best-effort hotfixes in offline
    environments.
    """

    raw = str(env.get("ANSIBLE_COLLECTIONS_PATH") or "").strip()
    if not raw:
        return []

    out: list[Path] = []
    seen: set[str] = set()
    for token in raw.split(":"):
        token = token.strip()
        if not token:
            continue
        base = Path(token).expanduser()
        candidates = [base] if base.name == "ansible_collections" else [base / "ansible_collections"]
        for candidate in candidates:
            try:
                resolved = str(candidate.resolve())
            except Exception:
                resolved = str(candidate)
            if resolved in seen:
                continue
            if candidate.is_dir():
                seen.add(resolved)
                out.append(candidate)
    return out


def _patch_text_remove_patroni_flush_handlers(text: str) -> tuple[str, bool]:
    """Remove the unconditional flush_handlers task from Autobase's patroni.yml.

    Autobase v2.5.2 flushes handlers immediately after templating patroni.yml,
    which can start Patroni before the role creates /var/log/patroni and before
    the role resets the data directory during bootstrap. That can lead to:
    - PermissionError writing /var/log/patroni/patroni.log
    - Partial DCS initialization and a stuck bootstrap (pg_isready retries)

    HybridOps applies this as a best-effort hotfix to improve initial bootstrap UX.
    """

    if "hyops-hotfix:autobase:patroni:remove-flush-handlers" in text:
        return text, False

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    removed = False

    i = 0
    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""

        if cur.lstrip().startswith("- name: Flush handlers") and "meta: flush_handlers" in nxt:
            removed = True
            i += 2
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        out.append(cur)
        i += 1

    if not removed:
        return text, False

    if not out or out[-1].endswith("\n"):
        out.append("\n")
    out.append("# hyops-hotfix:autobase:patroni:remove-flush-handlers\n")
    out.append("# rationale: avoid starting/reloading Patroni before bootstrap prerequisites are ready\n")
    return "".join(out), True


def apply_collection_hotfixes(*, ev: EvidenceWriter, result: dict[str, Any], env: dict[str, str]) -> None:
    """Apply best-effort hotfixes to known-problematic upstream collections."""

    applied: list[dict[str, str]] = []

    for root in _iter_ansible_collection_dirs(env):
        patroni_task = root / "vitabaks" / "autobase" / "roles" / "patroni" / "tasks" / "patroni.yml"
        if not patroni_task.exists():
            continue

        try:
            original = patroni_task.read_text(encoding="utf-8")
        except Exception:
            continue

        patched, changed = _patch_text_remove_patroni_flush_handlers(original)
        if not changed:
            continue

        try:
            tmp = patroni_task.with_suffix(patroni_task.suffix + ".hyops.tmp")
            tmp.write_text(patched, encoding="utf-8")
            tmp.replace(patroni_task)
        except Exception:
            continue

        applied.append(
            {
                "collection": "vitabaks.autobase",
                "file": str(patroni_task),
                "hotfix": "remove_flush_handlers",
            }
        )

    if applied:
        try:
            ev.write_json("ansible_hotfixes.json", {"applied": applied})
        except Exception:
            pass
        for item in applied:
            result.setdefault("warnings", []).append(
                f"ansible hotfix applied: {item['collection']} {item['hotfix']} ({item['file']})"
            )
