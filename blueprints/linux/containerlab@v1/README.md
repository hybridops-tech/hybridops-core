# Local Linux Containerlab

This blueprint runs Containerlab on Ubuntu 22.04 or 24.04, including Ubuntu
24.04 under WSL2. Core, Containerlab and the lab execute in the same Linux
environment. On WSL2, the access command opens the GUI in the Windows browser.

## Configure

```bash
hyops blueprint init --env containerlab-local --ref linux/containerlab@v1
hyops blueprint edit --env containerlab-local --ref linux/containerlab@v1
```

Set `containerlab_lab_source_dir` to the directory containing `lab.clab.yml`.
For IOL-XE, also set `containerlab_lab_local_image_dir` and
`containerlab_lab_local_image_dir_authorised_use: true`. Set
`containerlab_require_kvm` and `containerlab_healthcheck_require_kvm` to `true`
only for node kinds that require KVM.

## Run

```bash
hyops blueprint validate --env containerlab-local --ref linux/containerlab@v1
hyops blueprint preflight --env containerlab-local --ref linux/containerlab@v1
hyops blueprint deploy --env containerlab-local --ref linux/containerlab@v1 --execute
hyops blueprint access --env containerlab-local --ref linux/containerlab@v1 --automation
hyops blueprint device list --env containerlab-local --ref linux/containerlab@v1
```

The GUI uses the current Linux account. On WSL2, use the Ubuntu account and
password created during HybridOps.Core installation.

Protected teardown retains a verified recovery set. The next interactive
deploy offers recovery or a clean deployment. If the archived topology differs
from the controller source, select the authoritative version. Unattended runs
use `--restore-labs` for the archive or `--skip-lab-restore` for the controller
source.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-containerlab-local/)
