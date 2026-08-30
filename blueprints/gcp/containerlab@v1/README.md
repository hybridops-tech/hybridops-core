# Containerlab on GCP

`gcp/containerlab@v1` runs an operator-supplied Containerlab topology on private, nested-virtualisation-capable GCP compute. The VM has no public address; configuration and access use IAP.

Containerlab remains authoritative for topology, nodes, links and native save or snapshot behaviour. HybridOps manages host readiness, private access, recovery verification, reconstruction and compute release.

## Execution chain

```text
private network
  -> execution host
  -> Containerlab runtime
  -> native topology deployment
  -> health verification
  -> recovery gate
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy and set `containerlab_lab_source_dir` to the controller-side directory containing `lab.clab.yml` and its relative files:

```bash
hyops blueprint init --env <env> --ref gcp/containerlab@v1 --edit
```

Container images remain native references in the topology. The blueprint can verify declared references and optionally permit registry pulls. Licence material remains in its authorised source and must not be embedded in the public blueprint.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-containerlab/)
- [Existing lab migration](../../../README.md#existing-lab-migration)
- [Lifecycle and ownership](ARCHITECTURE.md)
- [Acceptance record](VALIDATION.md)
