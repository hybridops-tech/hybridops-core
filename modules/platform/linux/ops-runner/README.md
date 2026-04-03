# platform/linux/ops-runner

Bootstrap a Linux execution host with the HybridOps release and required tooling.

This module is intentionally generic:

- it can target a GCP runner, Azure runner, AWS runner, or on-prem control host
- it consumes state-driven inventory if you already created the VM with `platform/*/platform-vm`
- it installs from an unpacked HybridOps release root, not from a Git checkout requirement

The bootstrap ensures the runner has the minimum execution toolchain required by HybridOps drivers, including `git` for Terragrunt module sources.

When a blueprint composes a VM step plus `platform/linux/ops-runner`, treat the bootstrap as current-host convergence,
not historical evidence. If the VM is rebuilt or rehomed, rerun the bootstrap step instead of relying on an older
`status: ok` state record.

Cloud runner blueprints standardize on Ubuntu LTS images for the execution host. The on-prem execution-runner path also pins Ubuntu LTS so the VyOS `vyos-vm-images` builder and the runner bootstrap toolchain stay aligned on one validated Linux baseline.

## Typical use

1. Create a runner VM with a VM module or blueprint
2. Bootstrap the host with `platform/linux/ops-runner`
3. Use that host for `runner-local` DR and burst execution

Keep provider-specific egress separate from this module.
For example, the GCP runner blueprint composes Cloud NAT before VM bootstrap instead of embedding GCP networking logic here.

## Inventory

Use one of:

- explicit `inventory_groups`
- `inventory_state_ref` + `inventory_vm_groups`

For the GCP runner created by `networking/gcp-ops-runner@v1`:

```yaml
inventory_state_ref: "platform/gcp/platform-vm#gcp_ops_runner"
inventory_vm_groups:
  runner:
    - "runner-01"
```

## Release source

Set `runner_release_root` to the unpacked HybridOps release root on the controller that is executing this module.

If `runner_release_root` is empty, the module falls back to `HYOPS_CORE_ROOT`.

That keeps the workflow tarball-safe:

- an unpacked release directory is enough
- no Git checkout is required

For a more production-oriented runner flow, use:

- `runner_release_archive_url`
- optional `runner_release_archive_sha256`

That allows the runner to download a versioned HybridOps release tarball from an artifact repository instead of depending on a local unpacked tree on the controller.

When bootstrapping from a local unpacked release root, the controller vendors the already-installed HybridOps Python runtime dependencies from its active runtime and copies them into the staged release on the runner. The runner then executes HybridOps directly from the copied release payload, without network dependency resolution or PyPI access.

The module records the staged release archive hash on the runner and automatically reinstalls when that hash changes. That keeps runner refreshes aligned with the shipped payload without requiring a manual `runner_force_reinstall` toggle after every code update.

## Toolchain mode

Defaults:

- `runner_setup_base: true`
- `runner_setup_ansible: true`
- `runner_setup_cloud_gcp: false`
- `runner_setup_cloud_azure: false`

For a GCP runner, enable `runner_setup_cloud_gcp: true`.

## Access modes

`platform/linux/ops-runner` supports:

- `ssh_access_mode: direct`
- `ssh_access_mode: bastion-explicit`
- `ssh_access_mode: gcp-iap`

For private GCP runners, `gcp-iap` is the preferred bootstrap path.
When inventory is consumed from `platform/gcp/platform-vm` state, the module resolves the required GCP instance name, zone, and project metadata automatically.
The target runner VM must also carry the `allow-iap-ssh` tag, or the network must provide an equivalent firewall rule permitting TCP/22 from the IAP source range.
For freshly created runners, set a short `connectivity_wait_s` window so bootstrap tolerates the first-minute guest/IAP readiness lag.
IAP solves inbound management access only. Private runners still need outbound HTTPS egress for package and tool installation during bootstrap. In GCP that typically means Cloud NAT for the runner subnet, or an explicitly accepted public-IP egress posture for the runner host.

## Notes

- This module needs a real access path to the runner host. If the runner is private-only, bootstrap from a controller that can reach it, or use an explicit provider access path such as IAP or a bastion.
- `platform/linux/ops-runner` is the reusable bootstrap layer. The `networking/gcp-ops-runner@v1` blueprint composes VM creation plus runner bootstrap.
- `runner_sshd_gateway_ports`: when `true`, HybridOps manages `/etc/ssh/sshd_config.d/90-hybridops-runner.conf` with `GatewayPorts yes` and `AllowTcpForwarding yes`. Enable this for GCP DMS reverse-SSH source lanes.
