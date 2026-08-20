# platform/linux/containerlab-lab

Stages a user-owned Containerlab source directory on the managed host and runs the requested lab action through Containerlab.

The `.clab.yml` file remains authoritative and is copied unchanged with any relative local files it references. HybridOps does not convert it into a second topology format.

`containerlab_lab_source_dir` is a controller-side path and should be set in the runtime blueprint. Proprietary NOS images should stay out of public HybridOps source and be supplied from an image source the operator is authorised to use.
