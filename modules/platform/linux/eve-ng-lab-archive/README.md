# platform/linux/eve-ng-lab-archive

Preserves EVE-NG lab continuity independently of the execution host and restores verified state after reconstruction.

The primary archive contains learner-created lab definitions from `/opt/unetlab/labs`. A companion archive can also preserve stopped QEMU overlay state when the selected continuity policy requires writable node state to survive.

## Export

When `eveng_lab_archive_path` is empty, the primary archive is written to the environment artifact directory:

```text
artifacts/eveng/labs/eve-ng-labs.tar.gz
```

The module publishes the archive path, manifest, creation time and SHA-256.
A new archive replaces the current generation only after verification. The
preceding verified generation is retained as a fallback. A failed export leaves
the current archive unchanged.

For stopped-QEMU state, enable:

```yaml
eveng_lab_archive_include_node_state: true
eveng_lab_archive_stop_running_nodes: true
```

The archive role stops running QEMU nodes, validates their overlay disks and creates a separately checksummed node-state companion archive. Base images remain independently managed and are paired with the restored overlays on the reconstructed host.

## Restore

Restore verifies the recorded SHA-256 before applying the primary lab archive. When a verified node-state companion is present, the runtime supplies its path and checksum through:

```yaml
eveng_lab_archive_restore_node_state: true
eveng_lab_archive_node_state_path: <verified-companion-archive>
eveng_lab_archive_node_state_expected_sha256: <sha256>
```

Existing lab content and runtime disks remain protected unless overwrite is explicitly enabled.

EVE-NG blueprints use this contract as their archive-before-release path. A later deployment with `--restore-labs` selects and verifies the retained environment archive before restoration.
