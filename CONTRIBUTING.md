# Contributing to HybridOps Core

HybridOps Core is a contract-driven runtime for repeatable infrastructure
operations across cloud, on-prem, Kubernetes, and networking targets.

## Pull requests are welcome

For a contained improvement, open a pull request directly. You do not need to
ask for permission first.

Start with an issue when the work introduces a new provider surface, a new
architecture, a broad module family, or a behaviour change that needs design
agreement before implementation.

Useful contributions include:

- bug fixes and regression tests
- clearer CLI behaviour and validation errors
- module, blueprint, driver, and pack improvements
- execution, packaging, and infrastructure quality fixes
- preflight checks, probes, and run-record improvements
- accurate examples and operator documentation

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Dependencies vary by change. Install only what the area you are working on
requires. The repository checks below show the expected validation paths.

## Scope and conventions

- Keep one pull request focused on one problem.
- Do not include credentials, tokens, private addresses, customer data, or
  unredacted run records.
- Read the local `README.md` before changing a module or blueprint.
- Keep implementation-specific details in the selected driver and pack. A
  module should describe intent, inputs, validation, execution selection, and
  outputs.
- Keep shipped blueprints reusable. Do not hard-code private repository
  layouts, customer environments, credentials, or application-specific flows.
- Avoid broad formatting-only or unrelated refactors in a functional change.

## Module and blueprint changes

When adding or materially changing a module, include the pieces that make the
contract usable and reviewable:

- `spec.yml`
- a local `README.md`
- a minimal example under `examples/`
- tests or fixtures for changed behaviour
- preflight or probe updates when the delivered outcome changes

Blueprints sequence supported module chains. Keep policy, required upstream
state, and verification explicit in the blueprint contract.

## Validate your change

Use a focused check while working on the relevant area:

```bash
python3 -m unittest hyops.tests.test_cli
python3 tools/ci/check-module-catalog.py
```

Before opening a pull request, run the applicable full checks:

```bash
bash tools/ci/check-python.sh
bash tools/ci/check-ruff.sh
bash tools/ci/check-yaml.sh
bash tools/ci/check-shell.sh
bash tools/ci/check-ansible.sh
bash tools/ci/lint-ansible.sh
bash tools/ci/check-terraform.sh
```

GitHub Actions is the repository gate. In the pull request, state which checks
you ran locally and call out anything you could not run.

## Candidate validation

After the quality jobs pass, CI builds temporary installable candidates. A pull
request candidate is built from the prospective merge with `main`, so the
package is tied to the exact tree accepted by that CI run.

Use the candidate, rather than a source checkout, when a change needs acceptance
testing in a real environment. This is especially important for installation,
packaging, provider lifecycle, host integration, recovery, and other behaviour
that cannot be established by repository checks alone.

Before an acceptance run:

- download the candidate from the exact pull request run
- verify its checksum
- record the artifact name, workflow run, source SHA, and provenance
- install it through the normal product installation path

During the run, record the environment assumptions, the observed result, and
cleanup. Do not edit the installed payload to make a test pass. If the test uses
a development dependency, record its exact commit rather than only a branch
name.

Candidate artifacts are short-lived test outputs. They are not releases and
must not be presented or promoted as releases. Permanent distribution still
comes from the tagged release path. When a claim depends on the released
installation path, repeat the relevant acceptance check against the published
release before making that claim.

## Pull request description

Include:

- the problem being solved
- the change made
- the validation performed
- relevant provider or environment assumptions
- follow-up work deliberately left out of scope

Small, reviewable pull requests are easier to test, understand, and merge.

## Security

Do not report vulnerabilities in a public issue or pull request. Follow
[SECURITY.md](.github/SECURITY.md) instead.

## Plugin development

Plugin discovery is tolerant by default: a registration error is written as a
warning so the built-in command surface remains available. During plugin
development or CI, set `HYOPS_STRICT_PLUGINS=1` to make driver or validator
registration errors fail the command immediately.
