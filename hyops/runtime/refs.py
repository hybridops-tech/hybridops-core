# hyops/runtime/refs.py
"""
purpose: Canonical reference helpers (module_ref, pack_id, etc).
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Iterable
import re


_ALLOWED = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?$")
_TOKEN = re.compile(r"[a-z0-9]+")

# Namespace-like segments that should not be treated as credential providers.
_PROVIDER_STOPWORDS = frozenset(
    {
        "org",
        "core",
        "platform",
        "examples",
        "shared",
        "common",
        "onprem",
        "linux",
        "cloud",
        "network",
        # Cluster control-plane domains are typically kubeconfig-driven, not
        # provider-credential driven in hyops module specs.
        "k8s",
        "kubernetes",
    }
)

# Known provider tokens used to detect multi-provider module refs.
_KNOWN_PROVIDER_TOKENS = frozenset(
    {
        "gcp",
        "azure",
        "aws",
        "proxmox",
        "hetzner",
        "oci",
        "openstack",
        "vmware",
        "cloudflare",
        "digitalocean",
        "linode",
        "alicloud",
        "kubernetes",
        "k8s",
    }
)


def _infer_from_parts(parts: list[str]) -> list[str]:
    if not parts:
        return []

    inferred: list[str] = []

    # Primary token for path-like refs (pack_ref and provider-first identifiers).
    for token in _provider_tokens(parts[0]):
        if token in _KNOWN_PROVIDER_TOKENS and token not in _PROVIDER_STOPWORDS:
            inferred.append(token)

    # Secondary token for module_ref-like refs (<namespace>/<provider>/...).
    # Only known provider tokens should be inferred here. Generic capability
    # names like "postgresql-ha" are valid module families, not credentials.
    if len(parts) >= 2:
        for token in _provider_tokens(parts[1]):
            if token in _KNOWN_PROVIDER_TOKENS and token not in _PROVIDER_STOPWORDS:
                inferred.append(token)

    # Additional hints from later segments for multi-provider refs.
    for part in parts[2:]:
        for token in _provider_tokens(part):
            if token in _KNOWN_PROVIDER_TOKENS:
                inferred.append(token)

    return _unique(inferred)


def normalize_module_ref(value: str | None) -> str:
    v = (value or "").strip()
    if not v:
        return ""

    # Allow dot notation as a user-facing convenience.
    # Canonical storage remains slash-separated.
    v = v.replace(".", "/")

    # Collapse repeated separators.
    while "//" in v:
        v = v.replace("//", "/")

    parts = [p for p in v.strip("/").split("/") if p]
    if not parts:
        return ""

    # Refuse path traversal segments.
    if any(p in (".", "..") for p in parts):
        return ""

    v = "/".join(parts)
    if not _ALLOWED.fullmatch(v):
        return ""

    return v


def module_id_from_ref(module_ref: str) -> str:
    """
    Convert a canonical module_ref into a filesystem-safe module_id used in evidence paths.

    Norm:
      - module_ref is canonical (slash-separated).
      - module_id uses "__" as the separator.
    """
    v = normalize_module_ref(module_ref)
    if not v:
        return ""
    return v.replace("/", "__")


def _provider_tokens(segment: str) -> list[str]:
    return [t for t in _TOKEN.findall((segment or "").lower()) if t]


def _unique(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        k = (item or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def infer_credential_requirements(module_ref: str) -> list[str]:
    """
    Infer required credential providers from module_ref.

    Rules:
      - Primary source is module_ref segment #2 (<namespace>/<provider>/...).
      - Compound providers are supported via tokenization, e.g. gcp-azure or gcp+azure.
      - Additional providers can be inferred from later segments when they match known provider tokens,
        enabling refs like core/onprem/proxmox-sdn.
      - Namespace stopwords are filtered out.
    """
    v = normalize_module_ref(module_ref)
    if not v:
        return []

    parts = v.split("/")
    if len(parts) < 2:
        return []

    return _infer_from_parts(parts)


def infer_credential_requirements_from_pack_ref(pack_ref_id: str | None) -> list[str]:
    """
    Infer required credential providers from execution.pack_ref.id.

    Accepted examples:
      - azure/core/00-foundation-global/10-resource-group@v1.0
      - onprem/proxmox/core/00-foundation/10-network-sdn@v1.0
    """
    raw = (pack_ref_id or "").strip()
    if not raw:
        return []

    # Drop optional @version suffix.
    base = raw.split("@", 1)[0].strip()
    if not base:
        return []

    while "//" in base:
        base = base.replace("//", "/")

    parts = [p for p in base.strip("/").split("/") if p and p not in (".", "..")]
    if not parts:
        return []

    return _infer_from_parts(parts)
