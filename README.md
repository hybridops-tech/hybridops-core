<h1 align="center">HybridOps Core</h1>

<p align="center">
  <strong>A contract-driven runtime for governed infrastructure operations across hybrid environments.</strong>
</p>

<p align="center">
  HybridOps Core verifies authority, dependencies and recovery conditions before infrastructure changes advance, coordinates execution across systems, and retains a structured record of every transition.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT-0" src="https://img.shields.io/badge/license-MIT--0-blue.svg"></a>
  <a href="https://www.python.org/"><img alt="Python >= 3.11" src="https://img.shields.io/badge/python-%3E%3D3.11-blue"></a>
  <a href="https://github.com/hybridops-tech/hybridops-core/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/hybridops-tech/hybridops-core/actions/workflows/ci.yml/badge.svg"></a>
</p>

<p align="center">
  <a href="https://docs.hybridops.tech/guides/getting-started/quickstart/">Quickstart</a> ·
  <a href="https://docs.hybridops.tech/reference-scenarios/">Reference scenarios</a> ·
  <a href="https://docs.hybridops.tech">Documentation</a> ·
  <a href="https://hybridops.tech/papers">Technical papers</a>
</p>

## From declared intent to a reviewable operation

```mermaid
flowchart LR
    intent["Declared intent"] --> resolve["Resolve contracts<br/>and policy"]
    resolve --> preflight["Verify authority<br/>and dependencies"]
    preflight --> execute["Execute through a<br/>versioned driver and pack"]
    execute --> verify["Validate the<br/>result"]
    verify --> record["Publish outputs and<br/>write a run record"]
```

<table align="center">
  <tr>
    <td align="center"><strong>85</strong><br><sub>runtime modules</sub></td>
    <td align="center"><strong>30</strong><br><sub>reference blueprints</sub></td>
    <td align="center"><strong>52</strong><br><sub>public decision records</sub></td>
    <td align="center"><strong>8</strong><br><sub>supported targets</sub></td>
  </tr>
</table>

## Why HybridOps Core

Hybrid infrastructure operations carry authority, policy, dependency state, validation, recovery decisions and operating records across system boundaries. HybridOps Core brings those concerns into one stable operator contract while each native platform remains authoritative for its own resources.

A `ModuleSpec` defines intended capability. A `Profile` carries environment policy. A `Driver` binds execution. A versioned `Pack` carries implementation assets. A `Blueprint` composes modules into a dependency-aware lifecycle. The runtime resolves these contracts, performs preflight, executes the selected implementation, publishes outputs and writes a structured run record.

Core governs four connected stages:

- **contract resolution:** deterministic input merge, validation, dependency ordering and environment policy
- **controlled execution:** driver-based dispatch through versioned implementation packs and isolated workdirs
- **preflight and verification:** required conditions and module probes around execution
- **run records:** non-secret execution records with metadata, outputs and redacted logs

## Reference scenarios

HybridOps is exercised through complete platform paths rather than isolated configuration examples.

- **[Authoritative on-prem foundation](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/):** source-of-truth network and platform foundation
- **[PostgreSQL HA recovery cycle](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/):** backup continuity, failover, failback, and controlled cutover
- **[Kubernetes HA platform foundation](https://docs.hybridops.tech/reference-scenarios/gitops-kubernetes-foundation/):** highly available cluster foundation with GitOps delivery
- **[Network lab continuity](https://docs.hybridops.tech/reference-scenarios/network-lab-continuity/):** verified intake, private access, preservation and reconstruction for EVE-NG, GNS3 and Containerlab

See the full [reference scenario library](https://docs.hybridops.tech/reference-scenarios/).

## Quick start

For installation, workstation setup, target initialisation, and first-run guidance, see the [Quickstart](https://docs.hybridops.tech/guides/getting-started/quickstart/).

You can inspect blueprints locally without cloud credentials or a live environment. These commands validate the manifest and display the execution plan:

```bash
hyops blueprint validate --ref onprem/authoritative-foundation@v1
hyops blueprint plan --ref onprem/authoritative-foundation@v1
```

List local runtime environments without contacting their infrastructure:

```bash
hyops show env list
hyops show env list --json
```

See the [authoritative foundation blueprint](blueprints/onprem/authoritative-foundation@v1/) or browse the [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/).

If this operating model is useful to your work, star the repository to follow its development.

## Run records

Intent, policy, implementation and execution records remain separate. Blueprints add explicit ordering, required preflight evaluation and guarded lifecycle operations around the same runtime path.

Run records are written under stable paths such as:

```text
~/.hybridops/logs/module/<module_id>/<run_id>/
~/.hybridops/logs/init/<target>/<run_id>/
```

## Requirements

- Python >= 3.11
- Module-specific execution dependencies are documented with the relevant module and runbook

## Research and external review

HybridOps Core is the public reference implementation for ongoing work in platform engineering and infrastructure automation.

See [Research and External Review](RESEARCH.md) for published papers, implementation maps, and external technical reviews.

## Documentation

- **Full docs and reference scenarios:** [docs.hybridops.tech](https://docs.hybridops.tech)
- **Public site:** [hybridops.tech](https://hybridops.tech)
- **Contributing:** [Contribution guide](CONTRIBUTING.md)
- **Security:** [Security policy](.github/SECURITY.md)
- **Reference model:** [Anuket CNTT](https://cntt.readthedocs.io/en/latest/common/chapter00.html)

## License

[MIT-0](LICENSE)
