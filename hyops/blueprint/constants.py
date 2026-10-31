"""Blueprint command constants."""

from __future__ import annotations

import re


ACTION_SET = {"apply", "deploy", "plan", "validate"}
SUPPORTED_BLUEPRINT_API_VERSIONS = frozenset({"hybridops/v1"})
MODE_SET = {"bootstrap", "authoritative", "hybrid"}
PHASE_SET = {"bootstrap", "authoritative", "operations"}
ADDRESSING_MODE_SET = {"static", "dhcp", "ipam"}
LEGACY_AUTHORITY_SET = {"none", "netbox"}
BLUEPRINT_REF_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*@[a-z0-9][a-z0-9._-]*$")
STEP_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
