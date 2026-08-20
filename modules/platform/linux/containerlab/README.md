# platform/linux/containerlab

Prepares a Containerlab execution host and verifies the runtime capabilities required by the declared lab.

The module does not define or interpret Containerlab topology. The GCP reference blueprint enables nested virtualisation and requires KVM by default so VM-backed and vrnetlab workloads can run when the topology needs them.
