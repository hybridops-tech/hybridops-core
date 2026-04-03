# core/shared/manual-gate

Require an explicit operator acknowledgement before a sensitive control step proceeds.

This module is intentionally simple:

- no infrastructure is created
- no external system is mutated
- HybridOps records the declared gate decision in state

Use it when a workflow must stop until an operator confirms that out-of-band safety work is complete, for example:

- the old primary has been fenced
- provider-native promotion has already been performed
- a rebuilt target is ready for DNS cutback
- a change window has been approved

Typical usage:

```bash
hyops validate --env dev --skip-preflight \
  --module core/shared/manual-gate \
  --inputs "$HYOPS_CORE_ROOT/modules/core/shared/manual-gate/examples/inputs.min.yml"
```

Inputs:

- `gate_name`: short stable identifier for the decision point
- `gate_message`: operator-facing statement of what must already be true
- `confirm`: required to be `true` for `apply` or `deploy`; `validate` and `preflight` only check type and presence
- `assertions`: mapping of named boolean assertions; every provided assertion must be `true` for `apply` or `deploy`
- `evidence_notes`: optional list of brief human notes recorded in state

Example use cases:

- `dr/postgresql-cloudsql-promote-gcp@v1`
- `dr/postgresql-cloudsql-failback-onprem@v1`

This module exists to keep workflows honest:

- HybridOps can orchestrate repeatable steps
- but it must not pretend that provider-native promotion, fencing, or executive approval already happened

