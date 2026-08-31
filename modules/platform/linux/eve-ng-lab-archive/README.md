# platform/linux/eve-ng-lab-archive

Preserves EVE-NG lab continuity independently of the execution host and restores verified state after reconstruction.

The primary archive contains learner-created lab definitions from `/opt/unetlab/labs`. Before export, the module can ask EVE-NG to write saved device configurations into those definitions. A companion archive can preserve stopped QEMU overlay state.

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
eveng_lab_archive_guest_quiesced: true
```

Shut down stateful guests inside their operating systems, then stop the EVE-NG
nodes. The archive role rejects running QEMU processes, validates the overlay
disks and creates a separately checksummed node-state companion archive. Base
images remain independently managed and are paired with the restored overlays
on the reconstructed host.

To refresh saved device configurations before export, enable:

```yaml
load_vault_env: true
required_env: ["EVENG_ADMIN_PASSWORD"]
eveng_lab_archive_capture_device_configs: true
```

Capture uses the EVE-NG API on the target host. Failure stops the archive step and leaves the execution host in place.

## Restore

Restore verifies the recorded SHA-256 before applying the primary lab archive. When a verified node-state companion is present, the runtime supplies its path and checksum through:

```yaml
eveng_lab_archive_restore_node_state: true
eveng_lab_archive_node_state_path: <verified-companion-archive>
eveng_lab_archive_node_state_expected_sha256: <sha256>
```

Existing lab content and runtime disks remain protected unless overwrite is explicitly enabled.

A staged migration can also supply a checksummed image companion. The runtime
restores those referenced bases before lab definitions and QEMU overlays:

```yaml
eveng_lab_archive_restore_images: true
eveng_lab_archive_images_path: <verified-image-archive>
eveng_lab_archive_images_expected_sha256: <sha256>
eveng_lab_archive_overwrite_images: false
```

Image companions contain referenced QEMU, IOL or Dynamips bases only. They do
not contain IOL licence material. Image replacement is staged and promoted as
a separate transaction when overwrite is enabled explicitly.

EVE-NG blueprints use this contract as their archive-before-release path. A later deployment with `--restore-labs` selects and verifies the retained environment archive before restoration.
