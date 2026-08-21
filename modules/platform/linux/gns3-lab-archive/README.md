# platform/linux/gns3-lab-archive

Preserves GNS3 project continuity independently of the execution host and restores verified controller state after reconstruction.

The archive contains GNS3 project directories and controller metadata. Project directories carry topology files, project files and writable node disks.

Before export or restore, the archive role stops the GNS3 server so controller state is copied at a consistent lifecycle boundary. The service is started again before the operation completes.

Base images are independently managed by default and can be reconstructed from their declarations. Set `gns3_lab_archive_include_images` when the selected continuity policy also requires the image library in the retained set.

The default controller-side archive path is:

```text
artifacts/gns3/labs/gns3-labs.tar.gz
```

Export publishes the archive path, manifest, creation time, member list and SHA-256.

Restore requires the recorded checksum and verifies it before applying the retained project and controller state:

```yaml
gns3_lab_archive_action: restore
gns3_lab_archive_path: <verified-archive>
gns3_lab_archive_expected_sha256: <sha256>
```

GNS3 blueprints use this contract as their archive-before-release path. A later deployment with `--restore-labs` selects and verifies the retained environment archive before restoration.
