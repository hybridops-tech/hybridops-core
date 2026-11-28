# Contract validation, binding and dispatch

For a pending `ContinuityContract`, reconciliation records a `ContractValid`
condition for the observed generation. `True` means the specification passes
the versioned API checks. It does not grant authority or dispatch a stage.
`False` identifies the validation failure by reason code. If an existing
recovery claim cannot be matched to its declaration and producer, the
reconciler leaves status unchanged.

Status updates use the UID and resource version from a fresh read. If another
writer wins, the reconciler reads again. It checks the returned contract
identity, generation and condition before reporting a successful write.
An unchanged condition needs no write, including after a restart. Validation
skips deleting contracts and contracts past `Pending`.

## Reference binding

`bind_operation` reads the pending contract and resolves its workload and
parameter references in the contract namespace. It records each ConfigMap's
UID, resource version and content digest. For Secrets it requests only
metadata and records the UID and resource version. The declared workload
digest identifies the artifact, not the ConfigMap that describes it.

The binding is an immutable ConfigMap in a separate controller-owned
namespace. An initial bind that finds an existing record verifies it
without overwriting it. Retain the returned receipt before admitting any
workload action. To resume, pass that receipt to `verify_operation`;
do not call `bind_operation` again. A missing or replaced binding, or a
changed reference, stops verification. A contract status update alone
does not invalidate its binding.

## Bound execution

`run_bound_operation` executes a pending contract from its original receipt.
It accepts an inline workload identity, named adapters and authority declarations.
A workload or parameter reference that requires materialisation is refused
before claiming the operation.

Executors share one protected record namespace. Before dispatch, the executor
creates an immutable claim for the contract UID and marks the original binding
using its UID and resource version. An existing claim or dispatch marker
blocks a second execution. Retain both ConfigMaps and restrict writes to the
controller.
Before each stage or owned cleanup, the executor checks the live contract,
binding and claim again. A failed check leaves that action unexecuted.

An existing claim is never replayed, even from a fresh local operation store.
If an executor stops after claiming an operation, inspect the workload and
operation store. A missing terminal record does not establish whether an
action ran. Status reconciliation does not invoke execution or retry external
actions.

## Terminal status

When publishing terminal status, use `run_and_retain_terminal` **instead of**
`run_bound_operation`. It executes the contract once and retains the kernel's
committed `terminal.json` in an immutable ConfigMap in the contract namespace.
The controller records its UID and SHA-256 alongside the original dispatch
claim and pins that witness to the binding. A record larger than 1 MiB stays
in the operation store; Kubernetes status is not published.

Call `publish_terminal_status` with the original binding receipt. It checks
the current contract UID, generation and spec, verifies the stored bytes, and
derives the phase and recovery sets from the kernel record. A status conflict
repeats verification, not execution. After a lost response, use the same call;
it verifies an existing terminal status without rewriting it.

A restarted worker calls `reconcile(client, namespace, name, record_namespace=...)`
with the same protected record namespace used for dispatch. It reads the original
binding identity from the dispatch claim and verifies the pinned result before
publishing status. It does not need the first worker's receipt or operation store.
An undispatched contract follows normal validation; an incomplete dispatch stays
unresolved. Neither path runs the workload.

Retain the binding, dispatch claim, witness and evidence ConfigMaps without
owner references. Kubernetes does not update evidence and status atomically.
If execution stops before the witness is pinned, inspect the operation store
and workload; do not dispatch again to recover a missing status.

## Contract deletion

Retained execution claims the operation and attaches
`continuity.hyopsproject.github.io/terminal-evidence` before dispatch. Before
each stage or cleanup call, the executor checks that the contract is live and
the finalizer is still present. Deletion does not cancel a call already in
progress or retire the workload.

On deletion, reconciliation verifies the retained records and confirms terminal
status before removing its own finalizer. Status identifies the generation that
ran, not the generation Kubernetes assigns on deletion. A missing claim, unpinned
result or changed evidence keeps the finalizer in place. Inspect the workload
and operation store in that case; do not redispatch. Other finalizers and the
retained records are left intact.

Run the API-server checks with `bash tools/ci/check-continuity-api.sh`.

## Recovery evidence

A recovery set declares which stage produces it and the evidence name and
role to expect. Before the kernel records that stage as successful, the
adapter must return every declared identity with a valid SHA-256 digest,
even if no later stage uses the set. This checks the returned identity,
not the contents of the recovery artifact.

If a consumer requests a different role for the same declared evidence,
the kernel rejects the contract before admitting any stage.

## Retirement check

A destructive stage requires authority, a declared predecessor recovery set and
a retained-evidence reader. After admission and before dispatch,
the kernel streams every required artifact from that reader and compares its
SHA-256 with the producer's recorded digest. It repeats the check for each
destructive stage, then rechecks authority. A refused or changed authority,
or missing, unreadable or changed bytes, blocks dispatch.

The installed adapter declares its destructive operations in
`destructive_operations`. A contract cannot downgrade a listed operation by
omitting `destructive: true`. The reader resolves artifacts in independently
configured storage, not through a path supplied by a stage. Its open, read and
close operations must respect the supplied deadline. Each digest is checked
when read; storage must retain those versions through restore.

## Automatic cleanup

A stage's `recoveryOperation` requests cleanup; it does not authorise it.
An installed adapter may declare `owned_cleanup` as a frozenset of
`(forward_operation, recovery_operation)` pairs. A pair must only clean
up temporary state owned by that operation, preserving the workload and
retained recovery material for every supported input.

The kernel snapshots these capabilities before executing any stage. Without
a matching pair it records `recovery_effect_unverified`, skips that cleanup
and stops rollback of earlier stages. The terminal record keeps the
original failure reason.

Run the credential-free check with a new output directory:

```sh
python3 -m tools.acceptance.continuity_contract.runner --output ./continuity-proof
```

The `retire-restore` case uses separate local directories for source, retained
state and replacement. The missing- and changed-artifact cases leave the source
intact. Results are in `continuity-proof/report.json`.
