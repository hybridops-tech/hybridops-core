# platform/linux/pinned-workload

Runs an external workload at an exact Git commit and retains its declared
result paths outside the managed host.

The external repository owns its operation and acceptance checks. HybridOps
records the immutable source binding, exit status, host identity and checksum
of the retained evidence bundle. A failed entry point or missing evidence
retains the host and fails the module.

Protected runtime files can be staged with `pinned_workload_runtime_files`.
Their contents are not written to task output or the public execution manifest.

