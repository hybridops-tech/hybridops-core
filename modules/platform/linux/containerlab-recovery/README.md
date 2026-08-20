# platform/linux/containerlab-recovery

Controls the recovery check that runs before a disposable Containerlab host is removed.

During destroy, HybridOps asks Containerlab for the native save output required by the selected policy, creates an archive, copies it off-host, verifies the checksum, and only then allows host teardown to continue.

On a later deploy or rebuild, HybridOps imports the latest verified archive before the final Containerlab deploy. If the archive contains supported vrnetlab snapshots, they are passed back through `containerlab deploy --restore-all`. HybridOps does not interpret or rebuild the snapshot contents.

The GCP reference blueprint uses `rebuild` mode by default. `snapshot` and `ephemeral` retain different sets of state.
