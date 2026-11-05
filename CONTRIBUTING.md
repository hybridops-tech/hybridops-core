# Contributing to HybridOps Core

HybridOps Core is a contract-driven runtime for repeatable infrastructure
operations across cloud, on-prem, Kubernetes, and networking targets.

## Choose a contribution

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

Good starting points:

- [good first issues](https://github.com/hybridops-tech/hybridops-core/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22)
- [help wanted](https://github.com/hybridops-tech/hybridops-core/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22help%20wanted%22)
- [documentation issues](https://github.com/hybridops-tech/hybridops-core/issues?q=is%3Aissue%20is%3Aopen%20label%3Adocumentation)
- [open defects](https://github.com/hybridops-tech/hybridops-core/issues?q=is%3Aissue%20is%3Aopen%20label%3Abug)

## Contribution path

1. Choose one bounded outcome. Open or comment on an issue first when design
   agreement is required.
2. Fork the repository, or create a branch directly if you have write access.
3. Make the smallest complete change, including tests and documentation where
   the behaviour or operator path changes.
4. Run the focused checks for the affected area.
5. Open a Draft pull request when you need early review of the approach or
   validation plan.
6. Mark the pull request ready when it meets the requirements below.

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Dependencies vary by change. Install only what the area you are working on
requires. The repository checks below show the expected validation paths.

## Pull request requirements

A ready-for-review pull request must:

1. Deliver one bounded outcome without unrelated formatting or refactoring.
2. Link the relevant issue with `Closes #<number>` or `Fixes #<number>` when an
   issue exists. New provider surfaces, architectures, broad module families,
   and material behaviour changes require issue agreement before the pull
   request is marked ready for review.
3. Use `type(optional-scope): concrete outcome` as its title and keep the title
   within 72 characters.
4. Explain the problem, the resulting behaviour, the validation performed, and
   any deliberate exclusions or environment assumptions.
5. Include focused tests for changed behaviour and update documentation or
   examples when the public or operator-facing contract changes.
6. Contain no credentials, tokens, private addresses, customer data, generated
   runtime state, or unredacted run records.
7. Pass the applicable repository checks, or identify a check that could not be
   run and explain why.
8. Record the candidate artifact, source SHA, environment, result, and cleanup
   when acceptance depends on a real infrastructure environment.

A contained correction does not need a pre-existing issue. Draft pull requests
are welcome for early technical review but are not treated as ready to merge.

## Scope and conventions

- Read the local `README.md` before changing a module or blueprint.
- Keep implementation-specific details in the selected driver and pack. A
  module should describe intent, inputs, validation, execution selection, and
  outputs.
- Keep shipped blueprints reusable. Do not hard-code private repository
  layouts, customer environments, credentials, or application-specific flows.

## Title and authorship

Pull request titles become squash commit subjects and must use this form:

```text
type(optional-scope): concrete outcome
```

Allowed types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `release`, `revert`, `style`, and `test`. Keep the title within 72
characters and name the behaviour or artifact changed. Generic titles such as
`update`, `cleanup`, or `add files via upload` are rejected.

Use the name and email of the contributor responsible for the change.
Development environment metadata does not belong in authorship fields.

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

Use this map to select the minimum relevant checks:

| Change area | Focused validation |
|---|---|
| Python CLI or runtime | Relevant unit tests, `bash tools/ci/check-python.sh`, `bash tools/ci/check-ruff.sh` |
| Module or blueprint contract | Relevant catalog check, `bash tools/ci/check-yaml.sh`, affected contract tests |
| Shell, installer, or release packaging | `bash tools/ci/check-shell.sh` and the relevant install or release-manifest check |
| Configuration pack | `bash tools/ci/check-ansible.sh`, `bash tools/ci/lint-ansible.sh` |
| Infrastructure implementation | `bash tools/ci/check-terraform.sh` |
| Documentation or examples | `git diff --check` and any affected catalog or link check |

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

## Review and merge

Review checks the contract boundary, compatibility, failure handling,
validation, security, and documentation affected by the change. Keep requested
corrections in the same pull request unless a maintainer separates follow-up
work explicitly.

Pull requests are normally squash-merged after required checks and review pass.
Linked issues close only when their stated acceptance criteria are met.

## Conduct

Participation is governed by the HybridOps
[Code of Conduct](https://github.com/hybridops-tech/.github/blob/main/.github/CODE_OF_CONDUCT.md).

## Security

Do not report vulnerabilities in a public issue or pull request. Follow
[SECURITY.md](.github/SECURITY.md) instead.

## Plugin development

Plugin discovery is tolerant by default: a registration error is written as a
warning so the built-in command surface remains available. During plugin
development or CI, set `HYOPS_STRICT_PLUGINS=1` to make driver or validator
registration errors fail the command immediately.
