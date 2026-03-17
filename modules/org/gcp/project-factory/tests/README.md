# Module tests

## Local run (creates a run record)

```bash
rm -rf /tmp/hyops-e2e
./bin/hyops apply --root /tmp/hyops-e2e --module org/gcp/project-factory --inputs modules/org/gcp/project-factory/tests/example-inputs.yml
```
