# hybridops.common.decision_consumer

Installs the HybridOps decision consumer as a `systemd` service.

The consumer watches dispatch requests, waits for approval when required, and writes normalized execution records. It does not execute `hyops` in v1.
