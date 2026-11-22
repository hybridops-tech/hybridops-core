# Operation Authority Continuity

HybridOps enforces the authority required by an infrastructure operation at
admission and, when requested, verifies that authority again at completion.
The runtime contract is independent of the infrastructure module and the
system supplying authority. A blueprint declares a logical authority and a
capability, then binds that declaration to a provider:

```yaml
authorities:
  primary_ipam:
    capability: inventory_ipam
    provider: netbox

steps:
  - id: dependent_operation
    module_ref: platform/onprem/platform-vm
    contracts:
      addressing_mode: ipam
      requires_authority:
        ref: primary_ipam
        capability: inventory_ipam
```

The resolver checks that the binding exists, that its declared capability
matches the operation, and that the selected registered provider supports and
admits that capability. Any blueprint step can use the contract; generic
enforcement does not select a module, provider product, or deployment target.

## Shipped bindings

NetBox and Nautobot provide `inventory_ipam` authority. Kubernetes provides
`resource_authority` for an exact API object used as a cross-system control
record. The contract establishes whether a dependent operation may proceed; it
does not replace provider reconciliation.

### NetBox

NetBox preserves the existing HybridOps behavior. It resolves the established
shared-authority root, requires `platform/onprem/netbox` state to be `ok`, and
optionally performs the existing authenticated API probe. Canonical settings
are:

```yaml
authorities:
  primary_ipam:
    capability: inventory_ipam
    provider: netbox
    config:
      live_check: true
      verify_tls: true
      timeout_s: 5
      max_state_age_s: 3600
      instance_id: shared-netbox
```

`max_state_age_s` is optional. When set, absent, invalid, or older state
timestamps fail closed. NetBox endpoint and token discovery continue to use
`NETBOX_API_URL`, `NETBOX_API_TOKEN`, `HYOPS_NETBOX_AUTHORITY_ROOT`,
`HYOPS_NETBOX_AUTHORITY_ENV`, the runtime credentials file, and the encrypted
runtime vault.

### Nautobot

Nautobot uses its documented `/health/` readiness endpoint and then makes an
authenticated read of `/api/ipam/prefixes/?limit=1`. The second check proves
that the configured token can reach the IPAM API, rather than treating a web
server response alone as authority readiness.

```yaml
authorities:
  primary_ipam:
    capability: inventory_ipam
    provider: nautobot
    config:
      endpoint_env: NAUTOBOT_API_URL
      token_env: NAUTOBOT_API_TOKEN
      api_version: "2.4"
      verify_tls: true
      timeout_s: 5
      instance_id: shared-nautobot
```

The environment-variable names are configurable, but the token value is never
accepted in the blueprint. `endpoint` may be used instead of `endpoint_env`;
URLs containing user information, query strings, or fragments are rejected.
TLS verification is enabled by default. Probes reject redirects, and the
authenticated IPAM check requires a valid paginated JSON response.

The implementation follows the official Nautobot documentation for
[health checks](https://docs.nautobot.com/projects/core/en/stable/user-guide/administration/guides/health-checks/),
[REST authentication](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/rest-api/authentication/),
and the [versioned REST API](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/rest-api/overview/).

The shipped Nautobot scope is authority configuration, live readiness,
authenticated IPAM access, and attributable receipts. It does not add Nautobot
allocation, inventory import/export, or a Nautobot deployment module; those are
separate provider lifecycle capabilities.

### Kubernetes

The Kubernetes binding reads one exact API object before and after a dependent
operation. A fresh API read supplies the completion observation. The object's
UID and `metadata.resourceVersion` supply interval evidence when the object is
required to remain unchanged.

```yaml
authorities:
  change_control:
    capability: resource_authority
    provider: kubernetes
    config:
      resource_path: /api/v1/namespaces/platform/configmaps/change-authority
      endpoint_env: KUBERNETES_API_URL
      token_env: KUBERNETES_API_TOKEN
      verify_tls: true
      timeout_s: 5
      instance_id: platform-control-plane

steps:
  - id: dependent_operation
    module_ref: platform/example/dependent-operation
    contracts:
      requires_authority:
        ref: change_control
        capability: resource_authority
      authority_observation:
        expected_change: none
        on_unverifiable: fail
```

`endpoint` may replace `endpoint_env`. The API token remains environment-backed
and is never written to evidence. The endpoint must be an HTTPS origin; plain
HTTP is accepted only for loopback testing. `resource_path` must identify one
object under `/api/` or `/apis/`. TLS verification is enabled by default, and
redirects are rejected.

For `expected_change: none`, an unchanged UID and `resourceVersion` produce a
`stable` verdict. A revision change reports `drifted` even when the object's
content has returned to its original value. Object replacement also reports
`drifted`. A lower numeric completion revision is stale and fails closed.

The adapter does not claim writer attribution. A strict
`expected_change: operation` policy is rejected before dispatch because a
resource revision alone cannot separate the intended write from another actor's
write.

These semantics follow the Kubernetes API documentation for
[efficient change detection and resource versions](https://kubernetes.io/docs/reference/using-api/api-concepts/#efficient-detection-of-changes).

## Operator inspection

List the authority providers and capabilities available to the current
HybridOps installation:

```bash
hyops authority providers
```

Inspect authority outcomes from a normal blueprint deploy record:

```bash
hyops authority inspect --record /path/to/deploy.json
```

Inspection emits a deliberately limited view of the authority decision. It
does not reproduce provider endpoints, observation tokens, credentials, or
unrelated execution data. It validates the record schema and checks interval
decisions against the runtime policy, then reports a SHA-256 hash of the input
file. It does not authenticate a copied or externally supplied run record; use
the hash to bind exported inspection output to the retained source record. Add
`--json` to either command for structured output.

## Provider extensions

Optional providers are discovered through the Python entry-point group
`hyops.authority_providers`. Each entry point is a callable that receives the
authority registry and registers one or more providers:

```toml
[project.entry-points."hyops.authority_providers"]
service-management = "example_authority:register"
```

```python
def register(registry):
    registry.register(ServiceManagementAuthorityProvider())
```

Providers implement the admission interface and may implement interval
observation when their source can establish continuity. Duplicate provider
names are rejected. Provider names and immutable capability sets must already
be in canonical form. Discovery is atomic: if any entry point fails, none of
the discovered providers are installed and provider inventory reports the
failure. Provider distribution, version, entry point, and authority contract
version are recorded in runtime receipts.

Provider plugins execute as trusted in-process Python code with the same access
as HybridOps. Install them only from distributions whose code and release
provenance you trust. The current provider contract version is `1`.
`HYOPS_NO_PLUGINS=1` disables discovery;
`HYOPS_STRICT_PLUGINS=1` makes a plugin registration failure fatal.

## Fail-closed behavior and evidence

Missing bindings, unknown providers, unsupported or mismatched capabilities,
invalid configuration, non-ready state, stale bounded state, failed health
checks, unreachable endpoints, and rejected credentials all block the
dependent operation.

An admitted operation records a secret-free authority receipt in preflight and
module execution evidence. The receipt contains the logical reference,
capability, provider, verified state, result, safe instance/endpoint identity,
and available state run ID, update information, or Nautobot `API-Version`.
Credentials are never copied into the receipt.

## Interval observations

A step can require a second authority observation after successful dispatch:

```yaml
contracts:
  requires_authority:
    ref: primary_ipam
    capability: inventory_ipam
  authority_observation:
    expected_change: operation
    on_unverifiable: record
```

`expected_change` is `none` when the governed authority must remain unchanged,
or `operation` when the dispatched operation may produce an expected change.
The provider compares its native observations and returns an interval status of
`stable`, `drifted`, or `unverifiable`. It separately reports whether the
completion read is fresh. Drift or stale completion evidence always blocks the
step. `on_unverifiable: record` permits completion while retaining the weaker
verdict in the step record; the default is `fail`. When the selected provider
cannot establish the evidence required by `fail`, dispatch is rejected before
the operation starts.

Observation tokens identify provider state and must not contain credentials.
`observed_at` records when the authoritative read completed; revision,
generation or audit semantics remain provider-owned.

Nautobot supplies an authenticated live snapshot at each gate. Its completion
read is fresh. With `expected_change: none`, a changed snapshot reports
`drifted` and blocks the step. An unchanged snapshot remains `unverifiable`
because the binding does not consume audit history. NetBox bindings without
comparable observations are also `unverifiable`. Kubernetes provides strong
unchanged-object interval evidence through UID and `resourceVersion`; other
revision or audit semantics remain inside their provider adapters.

## Legacy NetBox form

Existing blueprints may continue to use:

```yaml
policy:
  ipam_authority: netbox
  netbox_live_api_check: false

contracts:
  addressing_mode: ipam
  requires_authority: netbox
```

This is an explicit compatibility form. It is translated to an internal
`legacy_netbox` logical declaration with capability `inventory_ipam` and the
NetBox provider. State-root resolution, state-only defaults, optional live API
checking, and the previous live-check TLS behavior are preserved. New
blueprints should use the canonical logical form.

## Acceptance benchmark

The fixed Kubernetes mutation scenarios live under
`tools/acceptance/authority_continuity/`. They verify stable, persistent-drift,
and reconverged-drift behavior against a disposable cluster. The benchmark and
its Terraform barrier are maintainer verification fixtures, not installed
runtime commands or supported infrastructure modules.
