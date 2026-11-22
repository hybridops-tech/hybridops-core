# Operation Authority Continuity benchmark

This acceptance benchmark verifies the production authority-continuity contract
against a disposable Kubernetes cluster. It is verification tooling, not a
runtime command or a supported infrastructure module.

The benchmark runs three fixed cases around a normal HybridOps module dispatch:

- the authority object remains unchanged;
- the authority object changes and remains changed;
- the authority object changes and returns to its original data.

The final case must still be denied because the Kubernetes resource revision
changed during the operation.

## Run

Run the benchmark from the root of a HybridOps Core Git checkout with Python
3.11 or later and the project dependencies installed. The host also requires a
running Docker daemon plus `git`, `kind`, `kubectl`, `terraform`, and
`terragrunt`.

```bash
python3 -m tools.acceptance.authority_continuity.runner
```

The default kind node image is pinned by digest. A formal run requires a clean
Git worktree. During development, `--allow-dirty-source` permits a run while
recording a deterministic hash of every tracked path and non-ignored untracked
path. The runner verifies that the source identity is unchanged after all
scenarios. Reports also record the Git revision, source-tree hash, node image
digest, and the versions of Docker, kind, kubectl, Terraform, and Terragrunt.
Blueprint and Terraform startup has a separate five-minute bound; `--timeout`
controls the operation window after the fixture opens it.

The disposable cluster is deleted by default. Secret-free reports are written
under `~/.hybridops/acceptance/authority-continuity/`. A custom `--out-dir`
must name a new directory outside the source checkout. A failed cluster cleanup
fails the benchmark and is recorded in the report.
