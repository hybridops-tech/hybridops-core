# platform/linux/gns3-starter-lab

Create a zero-image GNS3 teaching topology from built-in node types. The project
contains NAT, an Ethernet switch and two VPCS nodes.

An existing project is retained so tutor or learner changes are not overwritten.

```bash
hyops apply --env lab \
  --module platform/linux/gns3-starter-lab \
  --inputs modules/platform/linux/gns3-starter-lab/examples/inputs.min.yml
```
