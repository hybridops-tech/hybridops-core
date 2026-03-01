# docker_engine

Install and manage Docker Engine and the Docker Compose v2 plugin on supported Linux hosts.

Maintainer: HybridOps.Studio

## Summary

This role provides a small, opinionated Docker CE baseline suitable for control nodes, CI agents, and container-capable application hosts.

- Installs Docker Engine from the official Docker CE repositories.
- Installs the Docker Compose v2 plugin where available.
- Ensures the Docker daemon is running and optionally enabled at boot.
- Optionally adds users to the `docker` group.
- Fails fast on unsupported OS families to avoid partial configuration.

Design context: [ADR-0602 – Docker Engine baseline](https://docs.hybridops.studio/adr/ADR-0602-docker-engine-baseline/).

## Requirements

- Ansible 2.15+
- Python 3.10+ on the target host
- Network access to Docker CE repositories

## Supported platforms

- Ubuntu 22.04+
- Rocky Linux 9 / RHEL 9

## Role variables

Defaults live in `defaults/main.yml`.

| Variable | Default | Notes |
|---|---:|---|
| `docker_engine_state` | `present` | `present` installs and enables; `absent` removes and disables. |
| `docker_engine_enable` | `true` | Enables the `docker` service at boot when `true`. |
| `docker_engine_users` | `[]` | Users to add to the `docker` group (non-root Docker usage). |

## Behaviour

- Debian/Ubuntu:
  - Configures the Docker CE APT repository.
  - Installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin`.
- EL9 (Rocky/RHEL):
  - Configures the Docker CE YUM repository.
  - Installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin`.

A lightweight verification step runs `docker version` for diagnostics.

## Example playbook

```yaml
- name: Install Docker Engine baseline
  hosts: docker_hosts
  become: true
  gather_facts: true

  collections:
    - hybridops.common

  roles:
    - role: docker_engine
      vars:
        docker_engine_state: present
        docker_engine_enable: true
        docker_engine_users:
          - "{{ ansible_user | default('root') }}"
```

## License

- Code: [MIT-0](https://spdx.org/licenses/MIT-0.html)
- Documentation & diagrams: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

See the [HybridOps.Studio licensing overview](https://docs.hybridops.studio/briefings/legal/licensing/) for project-wide licence details, including branding and trademark notes.
