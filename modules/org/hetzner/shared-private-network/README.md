# org/hetzner/shared-private-network

Provision the reusable Hetzner private network used by the routed edge pair and the shared control host.

State-first contract:

- publishes `private_network_id` and `private_network_cidr`
- downstream modules consume it through `foundation_state_ref`

This module keeps shared network ownership separate from edge compute ownership. That lets operators destroy and rebuild the Hetzner edge pair without tearing down the shared control host network.

Example:

```bash
hyops validate --env dev --skip-preflight \
  --module org/hetzner/shared-private-network \
  --inputs "$HYOPS_CORE_ROOT/modules/org/hetzner/shared-private-network/examples/inputs.min.yml"
```
