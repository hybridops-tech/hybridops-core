# platform/network/decision-consumer

Deploy a deterministic decision consumer on the shared control host.

## What it does

- Runs a local consumer service under `systemd`.
- Watches dispatcher request files under `/opt/hybridops/decision-dispatcher/state/requests`.
- Verifies each request's declared approval identity before applying its approval posture.
- Waits for approval when a request requires approval.
- Verifies that approval still belongs to the exact approval-relevant request artefact.
- Emits normalized execution records under `/opt/hybridops/decision-consumer/state/executions`.

## Approval contract

Every request must retain the payload version and SHA-256 identity written by
the dispatcher. Its `dispatch_id` must also match the request filename. These
checks apply before the consumer evaluates `requires_approval`.

For a request with `requires_approval: true`, approval is not satisfied by the
presence of a record for the same `dispatch_id` alone.

The approval file remains named `<dispatch_id>.approved.json`, but it must bind
to the request's current approval identity:

- `dispatch_id`
- `approval_payload_version`
- `approval_artifact_sha256`
- `approved_by`
- `approved_at`
- optional `note`

See [`examples/approval.example.json`](examples/approval.example.json).

Immediately before promotion, the consumer recomputes the SHA-256 identity from
the current approval-relevant request contents. A missing or malformed approval
identity is invalid. A digest that no longer matches the current request is
stale. Neither condition can produce `approved-ready`.

`approved_by` and `approved_at` must be non-empty strings. A record without that
audit context is invalid.

The resulting execution record preserves the approved artefact identity and
approval context so later stages can retain provenance for what was actually
authorised.

Routes that explicitly set `requires_approval: false` retain their no-approval
semantics after request identity verification. Their execution records still
carry the current artefact identity for provenance.

## What it does not do in v1

- It does not execute `hyops`.
- It does not mutate dispatcher request files.
- Runner execution remains governed by the runner model.
- It does not authenticate filesystem writers or provide signed approvals. The
  request and approval directories remain trusted boundaries.
- It does not perform the separate final live-state precondition check that
  belongs at a real execution boundary.

Current v1 execution mode is:

- `approval-only`

That means the service promotes only requests that satisfy the applicable
approval contract into execution records that a later runner-aware executor can
consume.

## Why it exists

The control-plane split is deliberate:

1. `platform/network/decision-service` evaluates signals and emits a decision record.
2. `platform/network/decision-dispatcher` turns that record into a routed dispatch request and gives its approval-relevant contents an immutable identity.
3. `platform/network/decision-consumer` verifies approval against that identity and writes an execution record.
4. a later executor runs the approved record through the correct runner/module path.

This keeps policy evaluation, routing, approval, and execution as separate concerns.

## Usage

```bash
hyops validate --env dev \
  --module platform/network/decision-consumer \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-consumer/examples/inputs.min.yml"

hyops apply --env dev \
  --module platform/network/decision-consumer \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-consumer/examples/inputs.min.yml"
```
