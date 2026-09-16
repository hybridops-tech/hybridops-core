# platform/linux/containerlab-lab

Stages a user-owned Containerlab source directory on the managed host and runs the requested lab action through Containerlab.

The `.clab.yml` file remains authoritative and is copied unchanged with any relative local files it references. HybridOps does not convert it into a second topology format.

`containerlab_lab_source_dir` is a controller-side path and should be set in the runtime blueprint. Proprietary NOS images should stay out of public HybridOps source and be supplied from an image source the operator is authorised to use.

`containerlab_lab_local_image_archives` accepts absolute controller paths to authorised container image archives and verifies the expected image after loading.

`containerlab_lab_local_image_dir` discovers authorised IOL-XE sources from
standard CML image-definition YAML files or standard IOL-XE OCI archive names.
The role derives the image type, version, checksum and build reference.

`containerlab_lab_local_image_builds` builds operator-supplied 64-bit Cisco
IOL-XE binaries or supported OCI archives on the managed host through a pinned
vrnetlab revision. The declaration sets the source format, version, L3 or L2
type, optional checksum and authorised-use acknowledgement.
