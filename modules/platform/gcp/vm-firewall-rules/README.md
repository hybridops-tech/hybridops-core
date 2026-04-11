# platform/gcp/vm-firewall-rules

Create named GCP ingress (or egress) firewall rules scoped to network tags. Intended for use alongside
`platform/gcp/platform-vm` to add port-level access without modifying shared network infrastructure.

This module is policy-only: it does not provision VMs and has no dependency on any VM state.

## Prereqs

- `hyops init gcp --env <env>` completed.
- Target network exists (defaults to `default`).
- VMs that should be reached by a rule must carry the matching `target_tags` value.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `name_prefix` | `""` | Combined with `context_id` to form resource name prefix |
| `context_id` | `""` | Environment identifier |
| `project_id` | `""` | Optional override; defaults to env credentials |
| `network` | `"default"` | VPC network the rules apply to |
| `rules` | `[]` | List of rule objects (see below) |

Each entry in `rules` supports:

| Field | Required | Notes |
|---|---|---|
| `name_suffix` | yes | Appended to the prefix to form the GCP firewall rule name |
| `description` | no | Human-readable description |
| `direction` | no | `INGRESS` (default) or `EGRESS` |
| `priority` | no | 1–65534, default `1000` |
| `source_ranges` | no | CIDR list (INGRESS only) |
| `destination_ranges` | no | CIDR list (EGRESS only) |
| `target_tags` | no | Network tags that select which VMs the rule applies to |
| `allow` | yes | List of `{ protocol, ports }` blocks |

## Example

```yaml
name_prefix: platform
context_id: dev
network: default
rules:
  - name_suffix: allow-rdp
    description: RDP access for desktop VMs
    direction: INGRESS
    priority: 1000
    source_ranges:
      - "203.0.113.10/32"
    target_tags:
      - allow-rdp
    allow:
      - protocol: tcp
        ports: ["3389"]
  - name_suffix: allow-ssh
    direction: INGRESS
    source_ranges:
      - "203.0.113.10/32"
    target_tags:
      - allow-ssh
    allow:
      - protocol: tcp
        ports: ["22"]
```

## Usage

```bash
hyops apply --env dev \
  --module platform/gcp/vm-firewall-rules \
  --inputs my-firewall-rules.yml
```

## Outputs

- `rule_names` — map of `name_suffix → GCP rule name`
- `rule_ids` — map of `name_suffix → GCP resource ID`
