# platform/onprem/rke2-cluster

Install and reconcile an RKE2 cluster on existing Linux hosts via Ansible.

This module is capability-style: it does not provision VMs.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/onprem/rke2-cluster \
  --inputs "modules/platform/onprem/rke2-cluster/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/onprem/rke2-cluster \
  --inputs "modules/platform/onprem/rke2-cluster/examples/inputs.min.yml"
```

## Inputs

- `inventory_state_ref` (recommended): consume host inventory from `platform/onprem/platform-vm`.
- `inventory_requires_ipam` (default `true`): fail fast when inventory state is not NetBox-IPAM aligned.
- `required_env`: includes `RKE2_TOKEN` by default.

Use examples:

- `examples/inputs.min.yml`: single control plane baseline.
- `examples/inputs.typical.yml`: multi-node control plane + agents.

Operational note:

- Fresh converge after destroy is usually slower because nodes pull RKE2/runtime images and wait for CNI readiness.
- This is expected on cold nodes and is visible in evidence `ansible.log`.

## Outputs

- `kubeconfig_path`
- `rke2_servers`
- `rke2_agents`
- `cap.k8s.rke2 = ready`
