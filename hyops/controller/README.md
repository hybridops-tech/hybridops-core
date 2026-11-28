# Contract validation

For a pending `ContinuityContract`, reconciliation records a `ContractValid`
condition for the observed generation. `True` means the specification passes
the versioned API checks. It does not grant authority or dispatch a stage.
`False` identifies the validation failure by reason code.

Status updates use the UID and resource version from a fresh read. If another
writer wins, the reconciler reads again. An unchanged condition needs no
write, including after a restart. A deleting contract or a contract past
`Pending` is left untouched.

Run the API-server checks with `bash tools/ci/check-continuity-api.sh`.
