# platform/linux/eve-ng-lab-archive

Export learner-created EVE-NG lab definitions before workload teardown and
restore them after redeployment. The archive contains topology data under
`/opt/unetlab/labs`; device images and temporary node runtime data are not
included.

When `eveng_lab_archive_path` is empty during export, the archive is written to
the environment artifact directory:

```text
artifacts/eveng/labs/eve-ng-labs.tar.gz
```

Restore requires the archive path and its recorded SHA-256 checksum. Existing
lab content is protected unless `eveng_lab_archive_overwrite` is enabled.

EVE-NG blueprints use this contract directly. After a protected teardown, run
the same blueprint deployment with `--restore-labs` to restore the latest
verified archive for that environment.
