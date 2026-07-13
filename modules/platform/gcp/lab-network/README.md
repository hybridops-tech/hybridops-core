# platform/gcp/lab-network

Create a private GCP network for a disposable training or simulation lab.

The module owns one custom VPC, one regional subnet, IAP SSH ingress, one Cloud
Router, and Cloud NAT for the owned subnet. It is intended for isolated lab
environments that should not depend on the broader `org/gcp/wan-hub-network`
contract.

## Prerequisites

- `hyops init gcp --env <env>` is ready.
- The selected project has billing enabled and the required Compute Engine APIs.
  GCP init and module preflight validate billing before create/update operations;
  destroy remains available when billing is disabled.
- The operator can create VPC, firewall, router, and NAT resources.

## Security boundary

- The subnet does not provide a public IP to VMs by itself.
- IAP ingress permits TCP/22 only from the configured source CIDRs and only to
  instances with one of the configured target tags.
- Cloud NAT covers only the subnet owned by this module.
- No broad internal RFC1918 ingress rule is created.

The default IAP source range is Google's TCP-forwarding range. Change it only
when the provider contract changes and the replacement has been verified.

## Usage

Validate and run preflight:

```bash
hyops validate --env <env> \
  --module platform/gcp/lab-network \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/gcp/lab-network/examples/inputs.min.yml"

hyops preflight --env <env> --strict \
  --module platform/gcp/lab-network \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/gcp/lab-network/examples/inputs.min.yml"
```

Create the network:

```bash
hyops apply --env <env> \
  --module platform/gcp/lab-network \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/gcp/lab-network/examples/inputs.min.yml"
```

Destroy the network after all dependent VMs have been removed:

```bash
hyops destroy --env <env> \
  --module platform/gcp/lab-network \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/gcp/lab-network/examples/inputs.min.yml"
```

## Consuming the network state

`platform/gcp/platform-vm` can consume this module without driver-specific
logic:

```yaml
network_state_ref: "platform/gcp/lab-network"
subnetwork_output_key: "subnetwork_name"
assign_public_ip: false
tags:
  - "allow-iap-ssh"
```

## Outputs

The module publishes project, region, network, subnetwork, router, NAT, and IAP
firewall identities. Outputs contain no credentials.

## Non-goals

This module does not create projects, billing links, VMs, EVE-NG, device images,
teaching labs, VPNs, WAN routing, GKE secondary ranges, or NetBox state.
