# HybridOps project governance

## Scope

This governance covers HybridOps Core and the `common`, `helper`, and `app`
collection subprojects. It governs technical direction, contribution review,
releases, security coordination, and project assets.

Related projects are governed separately unless added through a public project
decision.

## Principles

- Technical decisions are made in the interests of the project and its users.
- Decisions, rationale, and implementation are public except for embargoed
  security matters.
- Maintainer authority is earned through sustained project work and is not
  attached permanently to a company or founder.
- Contributor access does not depend on employment, sponsorship, or foundation
  membership.
- Each subproject retains a clear technical responsibility and compatible
  release contract.

## Roles

### Contributor

Anyone who participates through issues, discussions, documentation, testing,
reviews, or code changes.

### Reviewer

A contributor trusted to triage issues and review changes in a documented area.
Reviewers may approve changes but do not merge, publish releases, or change
governance unless they also hold maintainer status.

### Maintainer

A contributor responsible for project direction, merge decisions, releases,
security response, and governance. Maintainers may have project-wide or
subproject responsibility recorded in [MAINTAINERS.md](MAINTAINERS.md).

## Decisions

- Routine changes use pull-request review and lazy consensus.
- Material contract, compatibility, security, or architecture changes begin in
  a public issue or discussion and record the accepted boundary before merge.
- Governance, project-scope, and subproject changes remain open for public
  comment for at least seven calendar days and require approval from two-thirds
  of all unconflicted maintainers.
- Releases require passing project checks and approval from a maintainer with
  release responsibility.
- Security matters follow the private reporting policy until coordinated
  disclosure.

Maintainers seek consensus first. If consensus cannot be reached, unconflicted
maintainers decide by simple majority and publish the outcome and rationale.
Maintainer removal and governance amendment require a two-thirds majority. With
one active maintainer, that maintainer may decide but must preserve every
required public review period and decision record.

## Communication

Official technical and governance work takes place through public GitHub
issues, discussions, and pull requests in the project repositories. A decision
made through another channel is not effective until its outcome and rationale
are recorded publicly.

The project does not require recurring meetings. If meetings are introduced,
their schedule, agenda, and notes will be public.

Embargoed security and confidential Code of Conduct matters use the private
channels defined by the relevant policy.

## Appointment

A reviewer or maintainer candidate must demonstrate sustained, constructive
work in the relevant area, sound technical judgement, dependable review, and
adherence to the [Code of Conduct](CODE_OF_CONDUCT.md).

An existing maintainer nominates the candidate through a public issue. The
nomination identifies the proposed responsibility and supporting work and
remains open for at least seven calendar days. Unconflicted maintainers decide
the nomination through the normal decision process.

There is no contribution quota, employment requirement, or paid route to a
project role.

## Inactivity, resignation, and removal

A reviewer or maintainer may resign at any time. A role may move to emeritus
status after twelve months without project activity, following public notice.
Emeritus maintainers retain attribution but not merge, release, or voting
authority.

A maintainer may be removed for sustained inactivity, repeated failure to meet
the role, security risk, or serious Code of Conduct breach. Removal follows a
public decision unless confidentiality is required for security, privacy, or
conduct reasons. The remaining unconflicted maintainers record the outcome and
apply the two-thirds voting threshold.

## Conflicts of interest

Maintainers disclose material employment, financial, or personal conflicts and
recuse themselves where the conflict could affect a project decision. Company
employment does not create a project veto or exclusive release right.

## Subprojects

Adding or removing a subproject requires:

1. a public proposal defining its responsibility, source, maintainers,
   licensing, and release relationship;
2. compatibility and security review;
3. the governance comment period; and
4. a recorded maintainer decision.

Inactive subprojects may be archived without archiving the whole project under
the same decision process.

## Security response

Maintainers with recorded security responsibility coordinate vulnerability
reports under the project [security policy](.github/SECURITY.md). They may add
qualified contributors to a private response group for a specific report.
Security access is removed when that responsibility ends.

## Code of Conduct

Participation is governed by the project
[Code of Conduct](CODE_OF_CONDUCT.md). A person involved in a report must not
participate in its resolution.

## Project resources

A proposal to obtain or transfer project resources begins in a public
governance issue. It follows the normal comment period and requires a simple
majority of all unconflicted maintainers unless it changes project scope,
governance, or transferred assets.

## Amendments

Changes to this governance follow the governance comment period and a recorded
maintainer decision. No amendment may grant permanent control to an individual
or organisation.
