# platform/linux/gns3-lab-archive

Export GNS3 projects and controller metadata before workload teardown and
restore them after redeployment. Project directories include topology files
and writable node disks.

Base images are excluded by default because the declared image step can
download them again. Set `gns3_lab_archive_include_images` only when the archive
must carry the image library.

The default controller-side archive path is:

```text
artifacts/gns3/labs/gns3-labs.tar.gz
```

Restore verifies the recorded SHA-256 checksum before replacing the freshly
generated GNS3 controller state.
