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
- `rke2_install_version`: explicit stable RKE2 release to install.

The module does not select a release channel or silently advance the cluster.
The older `rke2_role_vars.install_rke2_version` input remains supported for
existing environments.

Use examples:

- `examples/inputs.min.yml`: single control plane baseline.
- `examples/inputs.typical.yml`: multi-node control plane + agents.

Operational note:

- Fresh converge after destroy is usually slower because nodes pull RKE2/runtime images and wait for CNI readiness.
- This is expected on cold nodes and is visible in the run record `ansible.log`.

## Outputs

- `kubeconfig_path`
- `rke2_servers`
- `rke2_agents`
- `cap.k8s.rke2 = ready`

## Optional node storage prerequisites

- Set `enable_longhorn_prereqs: true` when the cluster will run Longhorn.
- Current tasks install the required node packages and enable `iscsid` before the RKE2 roles execute.
- Current package mapping:
  - Red Hat family: `iscsi-initiator-utils`, `nfs-utils`
  - Debian family: `open-iscsi`, `nfs-common`

## Multi-network nodes

Every Kubernetes node needs one node network that is mutually routable by the
other cluster nodes. In advanced `inventory_groups`, set `node_ip` and, for a
control-plane host, `advertise_address` to that address. These are ordinary
per-host inventory variables passed to the upstream RKE2 role; they may differ
from the SSH management address.

When recovery reconciles a server or agent registration endpoint, HybridOps
uses the first server's `advertise_address`, then `node_ip`, and only falls
back to its SSH address. This keeps the registration path on the routable
Kubernetes node network for multi-homed hosts.

When multi-homed nodes use valid asymmetric return paths, set
`rke2_reverse_path_filter_mode: loose`. The module persists Linux
`rp_filter=2` without restarting RKE2. Leave the default `preserve` when the
node network has symmetric routing. Do not change the advertised/node address
of an established embedded-etcd member in place; migrate or rebuild that
member instead.

```yaml
inventory_groups:
  rke2_servers:
    - name: rke2-cp-01
      host: 192.0.2.10          # SSH management address
      node_ip: 10.20.0.10       # Kubernetes node network
      advertise_address: 10.20.0.10
```

## Replacing a registration endpoint

Set `rke2_reconcile_agent_server: true` only when replacing the control-plane
registration endpoint used by existing agents. The module stops each affected
agent, removes every existing `server:` entry (including duplicated stale
entries), then sets the first declared `rke2_servers` host before starting the
agent again. Established etcd servers are not changed by this option.

Set `rke2_reconcile_server_config: true` only to recover a control-plane
configuration change that has left a server in an in-flight start. The module
stops and reconfigures one server at a time, then waits for it to be healthy
before continuing to the next member.

Set `rke2_upgrade_runtime_cleanup: true` only when an RKE2 version transition
needs a clean container-runtime boundary. When the installed release differs
from `rke2_install_version`, the module runs RKE2's bundled
`rke2-killall.sh`, verifies that old containerd shims are gone, and then lets
the pinned role install and start the requested release. RPM and role-supported
tarball paths are detected, including the configured RKE2 data directory. This
restarts pods on each serially processed node, so confirm workload redundancy
and maintenance tolerance before enabling it.

Operational note:

- The exported kubeconfig rewrites the default localhost server endpoint to the
  first control-plane node's `advertise_address`, then `node_ip`, and only falls
  back to its SSH management address when neither node-network value is set.
- Ensure your workstation can reach the selected API address. Otherwise, use a
  bastion or temporary SSH tunnel before running `kubectl` locally.
- Server and agent upgrades run one node at a time. Each node must report
  `Ready` through the Kubernetes API before the module advances.
- For control-plane host verification, use the bundled RKE2 client path:
  `/var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml`.
