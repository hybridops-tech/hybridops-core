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
- Terraform, Ansible, Packer, and shell quality fixes
- preflight checks, probes, and run-record improvements
- accurate examples and operator documentation

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Tool dependencies vary by change. Install only the tools needed for the area
you are working on, such as Terraform, Ansible, Packer, or ShellCheck.

## Scope and conventions

- Keep one pull request focused on one problem.
- Do not include credentials, tokens, private addresses, customer data, or
  unredacted run records.
- Read the local `README.md` before changing a module or blueprint.
- Keep tool-specific implementation in the selected driver and pack. A module
  should describe intent, inputs, validation, execution selection, and outputs.
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

The GitHub Actions suite is the final check. In the pull request, state which
commands you ran and call out anything you could not run locally.

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
