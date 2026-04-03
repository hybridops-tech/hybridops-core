"""Evidence helpers.

purpose: Backwards-compatible wrapper around hyops.runtime.evidence.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id

__all__ = ["EvidenceWriter", "init_evidence_dir", "new_run_id"]
