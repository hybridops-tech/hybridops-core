# platform/linux/pinned-workload

Runs an external workload at an exact Git commit and retains its declared
result paths with the controller.

The external repository owns its operation and acceptance checks. HybridOps
records the immutable source binding, exit status, execution target and checksum
of the retained evidence bundle. A failed entry point or missing evidence
retains the target and fails the module.

Protected runtime files can be staged with `pinned_workload_runtime_files`.
Their contents are not written to task output or the public execution manifest.

Host prerequisites required by the entry point can be declared with
`pinned_workload_packages`.

Checksummed operator-supplied Docker archives can be loaded with
`pinned_workload_container_image_archives`. Expected image IDs may be declared
when compute replacement requires the same image artifacts on every target.

## Usage

Initialise an environment-scoped input file, then validate and apply it through
a dedicated state instance:

```bash
ENV=<environment>
INSTANCE=<workload-id>
INPUTS="$HOME/.hybridops/envs/$ENV/config/modules/platform__linux__pinned-workload/instances/$INSTANCE.inputs.yml"

hyops module init \
  --env "$ENV" \
  --module platform/linux/pinned-workload \
  --state-instance "$INSTANCE"

hyops validate \
  --env "$ENV" \
  --module platform/linux/pinned-workload \
  --state-instance "$INSTANCE" \
  --inputs "$INPUTS"

hyops apply \
  --env "$ENV" \
  --module platform/linux/pinned-workload \
  --state-instance "$INSTANCE" \
  --inputs "$INPUTS"

hyops show module \
  --env "$ENV" \
  "platform/linux/pinned-workload#$INSTANCE"
```

The module supports state-resolved cloud inventory, direct SSH targets and
local Linux execution. The public
[operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/modules/hyops-pinned-workload-lifecycle/)
defines each target form and the before-and-after compute lifecycle check.
