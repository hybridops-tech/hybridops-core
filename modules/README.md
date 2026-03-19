# Modules Overview

HybridOps modules are the product's execution contract.

A module defines:

- the operator inputs it accepts
- the driver/profile/pack used to execute it
- the validation rules that must pass before execution
- the outputs it publishes back into runtime state

Modules do not embed tool-specific logic directly. Tool execution stays in the
selected driver and pack.

## Module contract

Each module ships a `spec.yml` with:

- `inputs.defaults`
- `execution.driver`
- `execution.profile`
- `execution.pack_ref.id`

Operators can then supply an inputs file to override defaults for a specific
environment or state instance.

## Resolution model

HybridOps resolves a module by:

1. loading `inputs.defaults`
2. overlaying the supplied operator inputs
3. validating the final input contract
4. executing the declared driver/profile/pack combination
5. publishing normalized state and outputs

When a module defines additional addressing or dependency contracts, those are
validated before execution. For example:

- `inputs.addressing.mode` must resolve to a supported mode such as `static` or `ipam`
- `ipam` flows must declare a supported provider such as NetBox and pass preflight checks

## Product direction

The module surface is stable and shipping today. Some framework features are
still evolving behind that stable surface, including:

- richer constraints
- broader probe-driven readiness publishing
- expanded output publishing helpers

Those improvements should extend the module contract, not replace it.
