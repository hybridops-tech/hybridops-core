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

Blueprint teardown supplies the acknowledgement from an environment action or
from `hyops blueprint destroy --guest-quiesced`. Manual acknowledgement is
scoped to that operation and must not be stored as a permanent blueprint input.

Configure the environment action once:

```bash
hyops blueprint quiescence edit \
  --env demo-lab \
  --ref gcp/eve-ng@v1

hyops blueprint destroy \
  --env demo-lab \
  --ref gcp/eve-ng@v1 \
  --archive-before-destroy \
  --execute
```

Core stores the action under the environment configuration and discovers it on
subsequent teardown. The script runs on the EVE-NG host. HybridOps then verifies
that no QEMU guest remains active and records the script checksum with the
archive evidence. `--quiesce-script` remains an operation-specific override.

## Device Configuration Export

To export and preserve Cisco IOL device configurations during lab preservation, enable:

```yaml
load_vault_env: true
required_env: ["EVENG_ADMIN_PASSWORD"]
eveng_lab_archive_capture_device_configs: true
eveng_lab_archive_config_export_timeout_s: 300
eveng_lab_archive_activate_saved_configs: true
```

### How it works

When `eveng_lab_archive_capture_device_configs` is enabled:

1. **Pre-export**: EVE-NG is instructed to write running device configurations into saved startup configurations
2. **Export**: Device configurations are exported using EVE-NG's native REST API (not as raw nvram files)
3. **Archive**: Configurations are stored in a device-config manifest within the archive
4. **Restore**: After recovery, the manifest is available for restoration using EVE-NG's native mechanism

### Configuration

- `eveng_lab_archive_capture_device_configs`: Enable device config capture (boolean)
- `eveng_lab_archive_config_export_timeout_s`: Maximum time to wait for export completion (1-3600 seconds)
- `eveng_lab_archive_activate_saved_configs`: Automatically activate saved configs during restore (boolean)
- `eveng_lab_archive_api_base_url`: EVE-NG API endpoint (default: `http://127.0.0.1`)
- `eveng_lab_archive_api_username`: EVE-NG API user (default: `admin`)
- `eveng_lab_archive_api_password_env`: Environment variable containing API password

### Capture behavior

**Before export**:
- Module calls EVE-NG API to request configuration export for each IOL device
- Waits up to configured timeout for operations to complete
- Exported configurations are read-only snapshots from the running devices
- Sensitive license material (iourc) is excluded from archive

**What is captured**:
- Device type and node ID
- Device configuration as formatted by IOL
- Capture timestamp and metadata
- Lab name and path

**What is NOT captured**:
- Raw IOL nvram_* runtime files (these are not portable across hosts)
- License keys or authentication material
- Dynamically allocated resources

### Restore behavior

Restored labs can recover device configurations through:

1. **Manual activation**: Administrators can apply saved configurations using EVE-NG UI
2. **Automated restore**: Using `eveng_lab_archive_activate_saved_configs: true` applies configs automatically
3. **Verification**: Restored devices are verified to have the expected configuration before acceptance

### Example workflow

```bash
# Export with device configuration capture
hyops module run platform/linux/eve-ng-lab-archive \
  --env production \
  -i eveng_lab_archive_action=export \
  -i eveng_lab_archive_capture_device_configs=true \
  -i eveng_lab_archive_config_export_timeout_s=600 \
  --execute

# Later, restore with configuration
hyops module run platform/linux/eve-ng-lab-archive \
  --env recovery \
  -i eveng_lab_archive_action=restore \
  -i eveng_lab_archive_path=/path/to/labs.tar.gz \
  -i eveng_lab_archive_expected_sha256=<checksum> \
  -i eveng_lab_archive_activate_saved_configs=true \
  --execute
```

### Troubleshooting

**Export timeout**: Increase `eveng_lab_archive_config_export_timeout_s` if you have many devices
**API connection failure**: Verify `eveng_lab_archive_api_base_url` and credentials
**Configs not restoring**: Check that `eveng_lab_archive_activate_saved_configs` is true for recovery
**Missing configurations**: Some device types may not support configuration export via EVE-NG API

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

Restore validates captured QCOW2 state without repairing or rewriting it.
Archive integrity does not guarantee that an appliance can boot its writable
state on a different hypervisor target. The restored guest must pass its own
boot and service checks before the migration is accepted.

EVE-NG blueprints use this contract as their archive-before-release path. A later deployment with `--restore-labs` selects and verifies the retained environment archive before restoration.
