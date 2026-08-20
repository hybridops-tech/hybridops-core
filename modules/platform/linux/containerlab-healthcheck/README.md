# platform/linux/containerlab-healthcheck

Checks the Containerlab runtime, pinned version, KVM when required, declared image references, topology validation, and the deployed lab state.

The module verifies that the expected lab is actually running without replacing Containerlab's own convergence or node-health behaviour.
