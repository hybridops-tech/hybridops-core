# dns_routing

Publishes DNS routing intent and can optionally execute a manual provider command.

v1 is safety-first:

- Intent is always written to state.
- DNS provider change requires explicit `dns_apply=true`.
- Provider execution path is `manual-command` only.
