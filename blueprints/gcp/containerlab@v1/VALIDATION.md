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
8. the original VM was removed after the recovery gate passed;
9. fresh GCP compute was created with a different resource identity;
10. retained recovery state verified and imported on the fresh host;
11. reconstruction used one native Containerlab deployment;
12. independent lab health passed again; and
13. final declared GCP compute was removed.

The acceptance path exercised the lifecycle boundary around Containerlab while Containerlab remained authoritative for topology, convergence, save, snapshot and restore semantics.

## Validated capability

The validation establishes the complete GCP continuity lifecycle implemented by HybridOps around Containerlab:

- continuity policy selects the recovery outcome required before compute release;
- the selected recovery set is retained and independently verified away from the execution host;
- that verification gates release of the original GCP compute;
- reconstruction occurs on fresh compute with a different resource identity;
- retained state is returned through native Containerlab deployment and restore behaviour;
- independent health verifies the reconstructed lab; and
- final execution compute reaches terminal state.

Recovery fidelity is selected by policy and delivered through the native capabilities of the topology and node types in use. Containerlab remains the authority for lab semantics, the operator remains the authority for image and licence rights, and GCP billing remains the authority for realised cloud spend.
