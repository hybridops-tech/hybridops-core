"""Vault helpers (ansible-vault-backed env file).

purpose: Read and update an ansible-vault encrypted env file in a controlled manner.
Architecture Decision: ADR-N/A (vault helpers)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import os
import shlex
import subprocess
import tempfile

from hyops.runtime.proc import run as run_proc


def _ansible_vault_env() -> dict[str, str]:
    env = os.environ.copy()
    # In restricted environments (CI/sandbox), ~/.ansible/tmp may not be writable.
    tmp_root = (env.get("TMPDIR") or "/tmp").strip() or "/tmp"
    env.setdefault("TMPDIR", tmp_root)
    env.setdefault("ANSIBLE_LOCAL_TEMP", str(Path(tmp_root) / "hyops-ansible-local"))
    try:
        Path(env["ANSIBLE_LOCAL_TEMP"]).expanduser().mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return env


def _resolve_default_vault_pass_script() -> Path | None:
    env_script = (os.environ.get("HYOPS_VAULT_PASS_SCRIPT") or "").strip()
    if env_script:
        candidate = Path(env_script).expanduser().resolve()
        if candidate.exists():
            return candidate

    env_root = (os.environ.get("HYOPS_CORE_ROOT") or "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve() / "tools" / "secrets" / "vault" / "vault-pass.sh"
        if candidate.exists():
            return candidate

    cur = Path.cwd().resolve()
    for _ in range(0, 8):
        candidate = cur / "tools" / "secrets" / "vault" / "vault-pass.sh"
        if candidate.exists():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "tools" / "secrets" / "vault" / "vault-pass.sh"
        if candidate.exists():
            return candidate

    return None



def _default_password_command_file() -> Path:
    # Workstation-level config (not per-env).
    return (Path.home() / ".hybridops" / "config" / "vault-password-command").resolve()


def _read_password_command_file() -> str | None:
    path = _default_password_command_file()
    if not path.exists():
        return None
    try:
        st = path.stat()
        # Refuse to execute if the file is writable by group/others (command injection risk).
        if (st.st_mode & 0o022) != 0:
            return None
        if st.st_uid != os.getuid():
            return None
    except Exception:
        return None

    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = str(raw or "").strip()
            if not line or line.startswith("#"):
                continue
            return line
    except Exception:
        return None
    return None


def resolve_default_password_command() -> str | None:
    command = (os.environ.get("HYOPS_VAULT_PASSWORD_COMMAND") or "").strip()
    if command:
        return command

    command = _read_password_command_file()
    if command:
        return command

    script = _resolve_default_vault_pass_script()
    if not script:
        return None
    return shlex.quote(str(script))


def _password_command_timeout_s() -> int:
    raw = (os.environ.get("HYOPS_VAULT_PASSWORD_COMMAND_TIMEOUT_S") or "").strip()
    if not raw:
        return 120
    try:
        timeout_s = int(raw)
    except ValueError:
        return 120
    if timeout_s < 5:
        return 5
    return timeout_s


def has_password_source(auth: "VaultAuth | None" = None) -> bool:
    if auth and (auth.password_file or auth.password_command):
        return True

    if (os.environ.get("HYOPS_VAULT_PASSWORD_FILE") or "").strip():
        return True
    if (os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE") or "").strip():
        return True
    if resolve_default_password_command():
        return True
    return False


def _password_command_hint(detail: str) -> str:
    msg = (detail or "").strip().lower()
    hints: list[str] = []
    if "entry not ready" in msg or "run --bootstrap" in msg:
        hints.append("run: hyops vault bootstrap")
    if (
        "cannot decrypt" in msg
        or "no pinentry" in msg
        or "public key decryption failed" in msg
        or "decryption failed" in msg
        or "pinentry" in msg
    ):
        hints.append("unlock GPG in this shell: hyops vault password >/dev/null")
    if (
        "tty required" in msg
        or "no controlling terminal" in msg
        or "not a tty" in msg
        or "no such device or address" in msg
    ):
        hints.append(
            "run from an interactive terminal (TTY), or set HYOPS_VAULT_PASSWORD_FILE for non-interactive runs"
        )
    if not hints:
        hints.append("verify vault password command, then run: hyops vault status-verbose")
    # Keep ordering stable while removing duplicates.
    uniq: list[str] = []
    seen: set[str] = set()
    for item in hints:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return "; ".join(uniq)


@dataclass(frozen=True)
class VaultAuth:
    password_file: str | None = None
    password_command: str | None = None

    def materialize_password_file(self) -> Path | None:
        """If password_command is used, materialize it into a 0600 temp file."""
        password_file = (self.password_file or os.environ.get("HYOPS_VAULT_PASSWORD_FILE") or os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE") or "").strip()
        if password_file:
            return Path(password_file).expanduser()

        password_command = (self.password_command or resolve_default_password_command() or "").strip()
        if not password_command:
            return None

        timeout_s = _password_command_timeout_s()
        try:
            r = run_proc(["/bin/sh", "-c", password_command], timeout_s=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"vault password command timed out after {timeout_s}s; "
                "command may be waiting for pinentry. "
                "unlock GPG in this shell (hyops vault password >/dev/null) "
                "or set HYOPS_VAULT_PASSWORD_FILE for non-interactive runs. "
                "You can also raise HYOPS_VAULT_PASSWORD_COMMAND_TIMEOUT_S."
            ) from exc
        if r.rc != 0:
            detail = ((r.stderr or "").strip() or (r.stdout or "").strip()).splitlines()
            suffix = f": {detail[0]}" if detail else ""
            hint = _password_command_hint(detail[0] if detail else "")
            raise RuntimeError(f"vault password command failed{suffix}; {hint}")

        pw = (r.stdout or "").strip()
        if not pw:
            raise RuntimeError(
                "vault password command returned empty output; "
                "verify the command prints only the vault password to stdout"
            )

        fd, tmp = tempfile.mkstemp(prefix="hyops.vaultpass.", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(pw + "\n")
            os.chmod(tmp, 0o600)
            return Path(tmp)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise


def _parse_env(text: str) -> dict[str, str]:
    def _unescape_env_value(value: str) -> str:
        out: list[str] = []
        idx = 0
        while idx < len(value):
            ch = value[idx]
            if ch != "\\" or idx + 1 >= len(value):
                out.append(ch)
                idx += 1
                continue
            nxt = value[idx + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            idx += 2
        return "".join(out)

    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        # remove surrounding quotes if present
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        v = _unescape_env_value(v)
        out[k] = v
    return out


def _render_env(env: Mapping[str, str]) -> str:
    def _escape_env_value(value: str) -> str:
        return (
            value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )

    lines = [
        "# purpose: HybridOps.Core bootstrap vault env (ansible-vault encrypted)",
        "# Architecture Decision: ADR-N/A (bootstrap vault env)",
        "# maintainer: HybridOps.Studio",
        "",
    ]
    for k in sorted(env.keys()):
        v = env[k]
        # Keep values single-line in the env file so multiline secrets survive
        # ansible-vault round-trips and can be reconstructed deterministically.
        escaped = _escape_env_value(v)
        lines.append(f'{k}="{escaped}"')
    lines.append("")
    return "\n".join(lines)


def read_env(vault_file: Path, auth: VaultAuth) -> dict[str, str]:
    vf = vault_file.expanduser()
    if not vf.exists():
        return {}

    pwf = auth.materialize_password_file()
    if pwf is None:
        raise RuntimeError("vault password required to read encrypted vault")

    try:
        r = run_proc(
            ["ansible-vault", "view", "--vault-password-file", str(pwf), str(vf)],
            timeout_s=30,
            env=_ansible_vault_env(),
        )
        if r.rc != 0:
            detail = ((r.stderr or "").strip() or (r.stdout or "").strip()).splitlines()
            suffix = f": {detail[0]}" if detail else ""
            raise RuntimeError(f"ansible-vault view failed{suffix}")
        return _parse_env(r.stdout)
    finally:
        if auth.password_command and pwf and str(pwf).startswith("/tmp/"):
            try:
                pwf.unlink()
            except FileNotFoundError:
                pass


def write_env(vault_file: Path, auth: VaultAuth, env: Mapping[str, str]) -> None:
    vf = vault_file.expanduser()
    pwf = auth.materialize_password_file()
    if pwf is None:
        raise RuntimeError("vault password required to write encrypted vault")

    vf.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_plain = tempfile.mkstemp(prefix="hyops.vaultenv.", dir=str(vf.parent), text=True)
    tmp_plain_path = Path(tmp_plain)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_render_env(env))
        os.chmod(tmp_plain, 0o600)

        r = run_proc(
            ["ansible-vault", "encrypt", "--vault-password-file", str(pwf), str(tmp_plain_path)],
            timeout_s=60,
            env=_ansible_vault_env(),
        )
        if r.rc != 0:
            detail = ((r.stderr or "").strip() or (r.stdout or "").strip()).splitlines()
            suffix = f": {detail[0]}" if detail else ""
            raise RuntimeError(f"ansible-vault encrypt failed{suffix}")

        os.replace(str(tmp_plain_path), str(vf))
        os.chmod(vf, 0o600)
    finally:
        try:
            tmp_plain_path.unlink()
        except FileNotFoundError:
            pass
        if auth.password_command and pwf and str(pwf).startswith("/tmp/"):
            try:
                pwf.unlink()
            except FileNotFoundError:
                pass


def merge_set(vault_file: Path, auth: VaultAuth, updates: Mapping[str, str]) -> dict[str, str]:
    existing = read_env(vault_file, auth)
    merged = dict(existing)
    for k, v in updates.items():
        if v is None:
            continue
        merged[str(k)] = str(v)
    write_env(vault_file, auth, merged)
    return merged
