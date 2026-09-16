# Containerlab on GCP

`gcp/containerlab@v1` runs an operator-supplied Containerlab topology on private, nested-virtualisation-capable GCP compute. The VM has no public address; configuration and access use IAP.

Containerlab remains authoritative for topology, nodes, links and native save or snapshot behaviour. HybridOps manages host readiness, private access, recovery verification, reconstruction and compute release.

## Execution chain

```text
private network
  -> execution host
  -> Containerlab runtime
  -> native topology deployment
  -> private browser interface
  -> health verification
  -> recovery gate
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy and set `containerlab_lab_source_dir` to the controller-side directory containing `lab.clab.yml` and its relative files:

```bash
hyops blueprint init --env <env> --ref gcp/containerlab@v1 --edit
hyops secrets ensure --env <env> CONTAINERLAB_GUI_PASSWORD
```

Container images remain native references in the topology. The blueprint can
verify declared references, permit registry pulls, load an authorised image
archive, or build an operator-supplied 64-bit Cisco IOL-XE binary or supported
OCI archive on the managed host through a pinned vrnetlab revision. Licence
material remains outside the public blueprint.

The examples include [a two-node Cisco IOL topology](examples/two-node-iol/lab.clab.yml)
with partial startup configurations. Directory discovery binds its image
reference to the single discovered L3 image.

## Access and recovery

The `hyops blueprint access` command opens the private browser interface and
can prepare direct node automation through the same IAP session. Sign in with
`opsadmin` and the stored `CONTAINERLAB_GUI_PASSWORD`. Save device changes to
native startup configuration before recovery. During protected destroy, the recovery gate
requests Containerlab's supported configuration export and retains the
inspected native lab directory with the declared source tree. The recovery set
is copied off the host and verified before compute release. The next deployment
restores the latest verified set. `hyops blueprint rebuild` performs those
phases as one operation.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-containerlab/)
- [Existing lab migration](../../../README.md#existing-lab-migration)
- [Lifecycle and ownership](ARCHITECTURE.md)
- [Acceptance record](VALIDATION.md)
