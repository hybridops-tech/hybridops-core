# DRAFT, DO NOT PUBLISH

Suggested issue title:

`Where should off-host recovery sit when the Containerlab host is disposable?`

## Draft body

I am integrating Containerlab with a GCP host lifecycle where the execution VM can be created for a lab run and removed afterwards.

Containerlab still owns the lab itself: `.clab.yml`, validation, nodes and links, deploy and convergence, native config save, supported vrnetlab snapshot and restore, generated lab data, and supported startup-config or licence handling.

HybridOps manages the host around it. Before deleting that host, HybridOps can require the selected Containerlab recovery data to be copied off-host and checksum-verified. On rebuild, the retained data is handed back to Containerlab rather than interpreted by HybridOps.

The integration also uses Containerlab's own `CLAB_LABDIR_BASE` so generated `clab-*` data stays separate from the operator topology and source tree.

```text
Containerlab: topology / validation / convergence / native recovery
                         |
---------------- ownership boundary ----------------
                         |
HybridOps: GCP host / readiness / off-host copy / rebuild / verification
```

I would value a view on two points:

1. If the Containerlab host is disposable, is it reasonable for HybridOps to require Containerlab-native recovery data to be retained off-host before that host is deleted?
2. Should HybridOps treat those recovery files as opaque and always hand restore back to Containerlab?

A short correction or counterexample is enough. There is no need to review the whole HybridOps repository.

Implementation references will be added only after the real GCP preserve, destroy, and fresh-host recovery test has passed.
