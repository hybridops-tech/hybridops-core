<h1 align="center">HybridOps Core</h1>

<p align="center">
  <strong>A contract-driven runtime for governed infrastructure operations across hybrid environments.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT-0" src="https://img.shields.io/badge/license-MIT--0-blue.svg"></a>
  <a href="https://www.python.org/"><img alt="Python >= 3.11" src="https://img.shields.io/badge/python-%3E%3D3.11-blue"></a>
  <a href="https://github.com/hybridops-tech/hybridops-core/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/hybridops-tech/hybridops-core/actions/workflows/ci.yml/badge.svg"></a>
</p>

<table align="center">
  <tr>
    <td align="center"><strong>80</strong><br><sub>runtime modules</sub></td>
    <td align="center"><strong>28</strong><br><sub>reference blueprints</sub></td>
    <td align="center"><strong>52</strong><br><sub>public decision records</sub></td>
    <td align="center"><strong>8</strong><br><sub>supported targets</sub></td>
  </tr>
</table>

---

## What this is

An individual control system can complete its work while the wider operation remains incomplete: an authority may be stale, a dependency unavailable, a result unverified, or teardown unfinished.

HybridOps Core governs that cross-system transition through a stable operator contract across environments, lifecycle stages, and implementation changes. Native platforms remain authoritative for their own resources; Core governs whether the wider operation may advance.

A `ModuleSpec` defines intended capability. A `Profile` carries environment policy. A `Driver` binds execution. A versioned `Pack` carries implementation assets. A `Blueprint` composes modules into a dependency-aware lifecycle. The runtime resolves these contracts, performs preflight, executes the selected implementation, publishes outputs, and writes a structured run record.

Core governs across these handoffs:

- **contract resolution:** deterministic input merge, validation, dependency ordering, and environment policy
- **controlled execution:** driver-based dispatch through versioned implementation packs and isolated workdirs
- **preflight and verification:** required conditions and module probes around execution
- **run records:** non-secret execution records with metadata, outputs, and redacted logs

## Reference scenarios

HybridOps is exercised through complete platform paths rather than isolated configuration examples.

- **[Authoritative on-prem foundation](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/):** source-of-truth network and platform foundation
- **[PostgreSQL HA recovery cycle](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/):** backup continuity, failover, failback, and controlled cutover
- **[Kubernetes HA platform foundation](https://docs.hybridops.tech/reference-scenarios/gitops-kubernetes-foundation/):** highly available cluster foundation with GitOps delivery

See the full [reference scenario library](https://docs.hybridops.tech/reference-scenarios/).

## Quick start

For installation, workstation setup, target initialisation, and first-run guidance, see the [Quickstart](https://docs.hybridops.tech/guides/getting-started/quickstart/).

Inspect a shipped blueprint locally:

```bash
hyops blueprint validate --ref onprem/authoritative-foundation@v1
hyops blueprint plan --ref onprem/authoritative-foundation@v1
```

See the [authoritative foundation blueprint](blueprints/onprem/authoritative-foundation@v1/) or browse the [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/).

## Execution model

```mermaid
flowchart LR
    spec["ModuleSpec / spec.yml<br/>intent contract"]
    cli["hyops apply<br/>merge and validate"]
    driver["Driver<br/>execute in workdir"]
    record["Run record<br/>redacted output"]
    profile["Profile<br/>policy and defaults"]
    pack["Pack<br/>implementation assets"]

    spec --> cli
    profile --> cli
    cli --> driver
    pack --> driver
    driver --> record
```

This boundary keeps intent, policy, implementation, and execution records separate. Blueprints add explicit ordering, required preflight evaluation, and guarded lifecycle operations around the same runtime path.

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
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Security:** [SECURITY.md](.github/SECURITY.md)
- **Reference model:** [Anuket CNTT](https://cntt.readthedocs.io/en/latest/common/chapter00.html)

## License

[MIT-0](LICENSE)
