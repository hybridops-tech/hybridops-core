"""Rendering/file helpers for the Packer image driver."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def hcl_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value or "")
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_runtime_vars(path: Path, values: dict[str, Any]) -> None:
    lines: list[str] = []
    for key in sorted(values.keys()):
        lines.append(f"{key} = {hcl_literal(values[key])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def derive_password_hash() -> str:
    prehashed = str(os.environ.get("SSH_PASSWORD_HASH") or "").strip()
    if prehashed:
        return prehashed

    plain = str(os.environ.get("SSH_PASSWORD") or os.environ.get("PACKER_SSH_PASSWORD") or "Temporary!").strip()
    if not plain:
        plain = "Temporary!"

    try:
        import crypt  # type: ignore[import-not-found]

        hashed = crypt.crypt(plain, crypt.mksalt(crypt.METHOD_SHA512))
        if hashed:
            return str(hashed).strip()
    except Exception:
        pass

    openssl = shutil.which("openssl")
    if openssl:
        try:
            proc = subprocess.run(
                [openssl, "passwd", "-6", "-stdin"],
                input=plain,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                out = str(proc.stdout or "").strip()
                if out:
                    return out
        except Exception:
            pass

    raise RuntimeError("unable to derive ssh password hash (set SSH_PASSWORD_HASH)")


def render_unattended_templates(template_work_dir: Path, *, admin_user: str, ssh_public_key: str, ssh_password_hash: str) -> None:
    http_dir = template_work_dir / "http"
    if not http_dir.is_dir():
        return

    for tpl in sorted(http_dir.glob("*.tpl")):
        out = tpl.with_suffix("")
        rendered = tpl.read_text(encoding="utf-8")
        rendered = rendered.replace("__VAR_ADMIN_USER__", admin_user)
        rendered = rendered.replace("__VAR_SSH_PUBLIC_KEY__", ssh_public_key)
        rendered = rendered.replace("__VAR_SSH_PASSWORD_HASH__", ssh_password_hash)
        out.write_text(rendered, encoding="utf-8")
        if out.name == "user-data":
            (http_dir / "meta-data").write_text("", encoding="utf-8")


def sync_shared_hcl(template_work_dir: Path, shared_dir: Path) -> tuple[list[Path], str]:
    if not shared_dir.is_dir():
        return [], ""

    copied: list[Path] = []
    for src in sorted(shared_dir.glob("*.pkr.hcl")):
        dst_name = "variables.pkr.hcl" if src.name == "variables.global.pkr.hcl" else src.name
        dst = (template_work_dir / dst_name).resolve()

        if dst.exists():
            try:
                if dst.read_bytes() != src.read_bytes():
                    return copied, f"shared file already exists with different content: {dst}"
            except Exception as exc:
                return copied, f"failed to compare shared file {dst}: {exc}"
            continue

        try:
            shutil.copy2(src, dst)
        except Exception as exc:
            return copied, f"failed to sync shared file {src.name}: {exc}"
        copied.append(dst)

    return copied, ""


def cleanup_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except Exception:
            continue
