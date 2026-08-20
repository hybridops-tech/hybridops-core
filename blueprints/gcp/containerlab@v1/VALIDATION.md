# GCP Containerlab lifecycle validation

Status: **validated**

The `gcp/containerlab@v1` lifecycle completed real-environment GCP acceptance before PR #303 was merged to Core `main`.

## Validated inputs

- Core PR: [#303](https://github.com/hybridops-tech/hybridops-core/pull/303)
- final feature head: `0645a7aa4440189cbb65a17c75512e276b467ce6`
- merge commit: `ec80a2b1e51d3c9233f9057f81bb7262fe3d7149`
- final Core CI run: `32416371036`, passed
- Containerlab: `0.78.0`
- released `hybridops.app` dependency: `0.1.9`

## Observed acceptance path

The end-to-end GCP run established all of the following:

1. private GCP execution compute was created;
2. IAP/SSH access succeeded;
3. nested virtualisation and KVM readiness passed;
4. Containerlab `0.78.0` was installed and verified;
5. the supplied topology deployed through native Containerlab;
6. independent lab health passed;
7. the selected recovery set was copied off-host and checksum-verified before original VM deletion;
8. the original VM was removed only after the recovery gate passed;
9. fresh GCP compute was created with a different resource identity;
10. retained recovery state verified and imported on the fresh host;
11. reconstruction used one native Containerlab deployment;
12. independent lab health passed again; and
13. final declared GCP compute was removed.

The acceptance path exercised the lifecycle boundary around Containerlab rather than replacing Containerlab topology, convergence, save, snapshot, or restore semantics.

## Claim boundary

This validation supports the tested GCP lifecycle: temporary execution compute can be released after the selected recovery state has been independently verified away from the host, and the lab can later be reconstructed on fresh compute through native Containerlab behaviour.

It does not claim:

- universal recovery fidelity for every Containerlab node kind;
- a replacement for Containerlab topology or recovery semantics;
- redistribution rights for proprietary network images;
- zero ongoing cost after compute release; or
- equivalent validation on every cloud or virtualisation platform.

Recovery fidelity remains determined by the selected policy and the native capabilities of the topology and node kinds involved.
