<!--
Purpose: Define privilege expectations for module execution (sudo handling).
Architecture Decision: ADR-0622
Maintainer: HybridOps.Studio
-->

# RB-040 — Privilege model

HybridOps.Core does not require sudo globally. Privilege requirements are declared per module.

## Module requirements

Each module declares:

- `requirements.privilege.local_sudo`
- `requirements.privilege.remote_sudo`

Values:

- `none`: module must not require sudo.
- `optional`: module may use sudo for convenience, but must fail safely without it.
- `required`: module requires sudo and must validate availability early.

## Operator expectations

- Prefer running modules from a designated automation host.
- Use least privilege for sudo where feasible.
