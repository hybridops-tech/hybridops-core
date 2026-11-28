# Contract validation and reference binding

For a pending `ContinuityContract`, reconciliation records a `ContractValid`
condition for the observed generation. `True` means the specification passes
the versioned API checks. It does not grant authority or dispatch a stage.
`False` identifies the validation failure by reason code. If an existing
recovery claim cannot be matched to its declaration and producer, the
reconciler leaves status unchanged.

Status updates use the UID and resource version from a fresh read. If another
writer wins, the reconciler reads again. It checks the returned contract
identity, generation and condition before reporting a successful write.
An unchanged condition needs no write, including after a restart. A deleting
contract or a contract past `Pending` is left untouched.

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

These functions verify identities; they do not dispatch adapters. The
controller installation must restrict writes to the record namespace.

Run the API-server checks with `bash tools/ci/check-continuity-api.sh`.

## Recovery evidence

A recovery set declares which stage produces it and the evidence name and
role to expect. Before the kernel records that stage as successful, the
adapter must return every declared identity with a valid SHA-256 digest,
even if no later stage uses the set. This checks the returned identity,
not the contents of the recovery artifact.

If a consumer requests a different role for the same declared evidence,
the kernel rejects the contract before admitting any stage.

Run the credential-free check with a new output directory:

```sh
python3 -m tools.acceptance.continuity_contract.runner --output ./continuity-proof
```
