# edge_observability

Install and manage edge observability services via Docker Compose on edge VPS nodes.

## Summary

This role deploys a lightweight observability stack on the edge (non-Kubernetes):
- Thanos Receive
- Thanos Query
- Thanos Store Gateway
- Grafana
- Alertmanager
- Thanos Ruler (optional)

It is designed to run alongside the WAN edge role, but remains operationally isolated.

## Requirements

- Ansible 2.15+
- Docker Engine + Compose v2 (via `hybridops.common.docker_engine`)

## Supported platforms

- Ubuntu 22.04+
- Rocky Linux 9 / RHEL 9

## Role variables

Defaults live in `defaults/main.yml`.

Key inputs:
- `edge_obs_objstore_config` (required when Thanos uses object storage)
- `edge_obs_hashring_endpoints` (required for Thanos Receive)
- `edge_obs_query_upstreams` (optional; defaults to local services)
- `edge_obs_alertmanager_config` (YAML)
- `edge_obs_grafana_admin_password` (use vault)

## Behaviour

- Renders config files into `/opt/hybridops/edge-observability/config`.
- Generates `docker-compose.yml` and a systemd unit.
- Uses Docker restart policies and systemd to survive reboots.
- Applies log rotation via Docker json-file limits.

## Example playbook

```yaml
- name: Edge observability services
  hosts: edge
  become: true
  gather_facts: true

  collections:
    - hybridops.common

  roles:
    - role: edge_observability
      vars:
        edge_obs_objstore_config: |
          type: GCS
          config:
            bucket: thanos-objstore-hybridops-blueprint
            service_account: |-
              { ... }
        edge_obs_hashring_endpoints:
          - "edge-1.internal:10907"
          - "edge-2.internal:10907"
        edge_obs_grafana_admin_password: "{{ vault_grafana_admin_password }}"
```

## License

- Code: [MIT-0](https://spdx.org/licenses/MIT-0.html)
- Documentation & diagrams: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
