"""Runtime credential discovery and env export helpers.

purpose: Translate runtime credentials files into stable driver env exports.
Architecture Decision: ADR-N/A (runtime credentials)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import re


_SUFFIX_KIND: tuple[tuple[str, str], ...] = (
    (".credentials.tfvars", "TFVARS"),
    (".credentials.env", "ENV_FILE"),
    (".credentials.json", "JSON_FILE"),
)

_PROVIDER_EXPORT_RE = re.compile(r"^HYOPS_([A-Z0-9_]+)_(TFVARS|ENV_FILE|JSON_FILE|CREDENTIALS_FILE)$")
_TFVARS_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _provider_key(raw: str) -> str:
    p = re.sub(r"[^A-Za-z0-9]+", "_", (raw or "").strip())
    p = p.strip("_")
    return p.upper()


def provider_env_key(provider: str) -> str:
    """Normalize a provider token into HYOPS env-key provider format."""
    return _provider_key(provider)


def discover_credential_env(credentials_dir: Path) -> dict[str, str]:
    exports: dict[str, str] = {}

    if not credentials_dir.is_dir():
        return exports

    for item in sorted(credentials_dir.iterdir(), key=lambda x: x.name):
        if not item.is_file():
            continue

        name = item.name
        resolved = str(item.resolve())

        for suffix, kind in _SUFFIX_KIND:
            if not name.endswith(suffix):
                continue

            provider = _provider_key(name[: -len(suffix)])
            if not provider:
                break

            exports[f"HYOPS_{provider}_{kind}"] = resolved
            exports.setdefault(f"HYOPS_{provider}_CREDENTIALS_FILE", resolved)
            break

    return exports


def available_credential_providers(exports: Mapping[str, str]) -> set[str]:
    """Extract provider keys available in HYOPS credential exports."""
    providers: set[str] = set()
    for key in exports.keys():
        m = _PROVIDER_EXPORT_RE.fullmatch(str(key).strip())
        if not m:
            continue
        provider = m.group(1).strip()
        if provider:
            providers.add(provider)
    return providers


def apply_runtime_credential_env(env: dict[str, str], credentials_dir: str | Path | None) -> dict[str, str]:
    if not credentials_dir:
        return {}

    base = Path(credentials_dir).expanduser().resolve()
    exports: dict[str, str] = {"HYOPS_CREDENTIALS_DIR": str(base)}
    exports.update(discover_credential_env(base))

    env.update(exports)
    return exports


def parse_tfvars(path: Path) -> dict[str, str]:
    """Parse a minimal subset of `*.tfvars` format into key/value strings."""
    values: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = _TFVARS_LINE_RE.match(line)
        if not m:
            continue

        key = m.group(1).strip()
        value = m.group(2).strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        values[key] = value

    return values
