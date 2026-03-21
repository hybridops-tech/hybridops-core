# platform/k8s/kube-dns-stub-domain

Configure `kube-dns` stubDomains on an existing Kubernetes cluster.

This module is intended for clusters that still use `kube-dns`, such as the
current GKE burst lane. It lets HybridOps publish a DNS forwarding contract in
state instead of relying on manual `kubectl` edits.

Use this module when a workload lane must resolve a private DNS zone through a
reachable authoritative resolver, for example a PowerDNS authority.

## Inputs

- `kubeconfig_path` or `kubeconfig_state_ref`
- `namespace`
- `configmap_name`
- `stub_domain`
- `dns_server_ips`
- `powerdns_state_ref`
- `powerdns_state_env`
- `kubectl_bin`

Resolution rules:

- `kubeconfig_state_ref` is the preferred way to consume cluster access.
- When `powerdns_state_ref` is set and `dns_server_ips` is empty, HybridOps
  derives the resolver IP from PowerDNS state.
- Explicit `dns_server_ips` remains available as an override.

Lifecycle:

- `apply` adds or updates the requested stubDomain.
- `destroy` removes the requested stubDomain from `kube-dns`.

## Usage

```bash
hyops validate --env dev \
  --module platform/k8s/kube-dns-stub-domain \
  --inputs modules/platform/k8s/kube-dns-stub-domain/examples/inputs.powerdns.yml

hyops apply --env dev \
  --module platform/k8s/kube-dns-stub-domain \
  --inputs modules/platform/k8s/kube-dns-stub-domain/examples/inputs.powerdns.yml
```
