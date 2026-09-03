# On-Prem RKE2 Cluster

Build the base template, provision RKE2 VMs, and install an on-prem RKE2 cluster.

Outcome: RKE2 is installed and kubeconfig is exported for operators.

## Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/onprem/rke2-cluster
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Prerequisites

Before running this blueprint, ensure:

- `hyops --help` succeeds.
- Proxmox initialization is complete for the target environment.
- Vault decryption works for the target environment.
- NetBox authority is ready and provides authoritative IPAM.
- SSH key access to the provisioned hosts is available.
- `RKE2_TOKEN` exists in the runtime vault.

If NetBox authority is not ready, bootstrap the shared foundation first:

```bash
hyops blueprint deploy --env shared --ref onprem/bootstrap-netbox@v1 --execute
```

Ensure the RKE2 token exists:

```bash
hyops secrets ensure --env <env> RKE2_TOKEN
```

For source-checkout usage, set `HYOPS_CORE_ROOT` to the repository root before running HyOps commands.

## Usage

Validate the blueprint:

```bash
hyops blueprint validate --ref onprem/rke2@v1 --blueprints-root blueprints
```

Review the execution plan:

```bash
hyops blueprint plan --ref onprem/rke2@v1
```

Run preflight:

```bash
hyops blueprint preflight --env <env> --ref onprem/rke2@v1 --blueprints-root blueprints
```

Deploy the complete blueprint:

```bash
hyops blueprint deploy --env <env> --ref onprem/rke2@v1 --blueprints-root blueprints --execute
```

The blueprint executes these steps in order:

1. `core/onprem/template-image` — build the Rocky 9 template.
2. `platform/onprem/platform-vm` — provision the RKE2 VMs using NetBox IPAM and shared SDN state.
3. `platform/onprem/rke2-cluster` — install and configure RKE2.

## Verification

A successful blueprint run ends with `status=ok`, and the RKE2 capability reports:

```text
cap.k8s.rke2 = ready
```

The exported kubeconfig is stored at:

```text
$HOME/.hybridops/envs/<env>/state/kubeconfigs/rke2.yaml
```

Verify that the cluster nodes are ready:

```bash
KUBECONFIG="$HOME/.hybridops/envs/<env>/state/kubeconfigs/rke2.yaml" kubectl get nodes -o wide
```

The kubeconfig server endpoint points to the first control-plane node's management IP. If the workstation cannot reach the management subnet, use the Proxmox jump host or another routed management path before running `kubectl`.

## Related documentation

- [Deploy RKE2 Cluster (HyOps Blueprint)](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-rke2/)
- [Operate RKE2 Cluster Module (HyOps)](https://docs.hybridops.tech/ops/runbooks/platform/modules/hyops-rke2-cluster-lifecycle/)
- [Operate Generic Platform VMs (HyOps)](https://docs.hybridops.tech/ops/runbooks/platform/modules/hyops-platform-vm-lifecycle/)
- [Build Proxmox VM Templates (HyOps)](https://docs.hybridops.tech/ops/runbooks/platform/modules/packer-proxmox-template-build/)
- [Proxmox SDN operations runbook](https://docs.hybridops.tech/ops/runbooks/networking/sdn_operations/)
