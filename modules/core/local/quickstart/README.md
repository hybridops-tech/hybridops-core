# Local quickstart operation

This module provides the credential-free first-run path used by `hyops quickstart`.
It manages one deterministic JSON artifact inside the isolated quickstart runtime
and exercises the standard module resolution, preflight, evidence, state, and
destroy lifecycle.

It does not execute shell commands, contact external services, or write outside
the selected runtime.
