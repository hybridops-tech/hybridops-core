# platform/onprem/rke2-etcd-member

Safely decommission one unhealthy embedded-etcd member from an existing RKE2
cluster. This is a lifecycle operation for a failed control-plane host; it does
not provision replacement VMs or install RKE2.

## Safety model

- The maintenance operator is resolved from `platform/onprem/platform-vm`
  state by default and must be NetBox-IPAM backed.
- The target is identified by an **exact** live etcd member name and peer URL.
  The module resolves the member ID at runtime; a mismatch fails without a
  change.
- The operation cannot remove its own operator member.
- At least two other etcd members must remain and each must pass an etcd health
  check before removal.
- `member_removal_confirm=true` is required.
- The Kubernetes Node object is removed after etcd membership by default. Set
  `remove_kubernetes_node: false` only when managing that object separately.

`hyops plan` performs all discovery and health checks in read-only mode. It
does not remove membership. `hyops apply` performs the removal after the same
checks pass.

## Example

```yaml
inventory_state_ref: platform/onprem/platform-vm#rke2_vms
inventory_vm_groups:
  rke2_operator:
    - rke2-cp-02
inventory_requires_ipam: true
ssh_private_key_file: ~/.ssh/id_ed25519
ssh_proxy_jump_auto: true

etcd_member_name: rke2-cp-01.example.internal-abcd1234
etcd_member_peer_url: https://10.10.0.2:2380
kubernetes_node_name: rke2-cp-01.example.internal
member_removal_confirm: true
```

Run it normally:

```bash
hyops preflight --env <env> --module platform/onprem/rke2-etcd-member --inputs <inputs.yml>
hyops plan --env <env> --module platform/onprem/rke2-etcd-member --inputs <inputs.yml>
hyops apply --env <env> --module platform/onprem/rke2-etcd-member --inputs <inputs.yml>
```

After removal, reconcile the replacement control-plane node with
`platform/onprem/rke2-cluster`.
