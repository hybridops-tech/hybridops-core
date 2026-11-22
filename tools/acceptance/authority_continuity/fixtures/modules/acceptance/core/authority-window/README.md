# acceptance/core/authority-window

This fixture opens a bounded operation window used by the authority continuity
benchmark. It exercises the normal module and Terragrunt lifecycle while the
benchmark runner coordinates an authority change. It does not implement authority
detection itself.

Run the complete benchmark instead of invoking this fixture directly:

```bash
python3 -m tools.acceptance.authority_continuity.runner
```

The barrier directory must be an existing absolute directory dedicated to one
run. `run_nonce` identifies the run, and `timeout_s` bounds how long the module
waits for the benchmark runner to release the operation.
