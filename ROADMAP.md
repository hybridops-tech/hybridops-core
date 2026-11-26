# HybridOps project roadmap

This roadmap records current project priorities. Detailed design and acceptance
criteria remain in linked issues and pull requests.

## Contract enforcement

- Complete fail-closed blueprint and module input enforcement
  ([#425](https://github.com/hybridops-tech/hybridops-core/issues/425)).
- Define brownfield emergency authority-transition semantics
  ([#293](https://github.com/hybridops-tech/hybridops-core/issues/293)).
- Make selected-plugin registration failure explicit where strict operation is
  required
  ([#277](https://github.com/hybridops-tech/hybridops-core/issues/277)).

## Project completeness

- Maintain the public `common`, `helper`, and `app` collection source as
  governed subprojects.
- Establish one compatibility record across Core and required subproject
  releases.
- Keep required operator and contributor documentation in a public
  contribution path.
- Maintain a complete source, dependency, and licence inventory.

## Release and security

- Maintain an explicit supported stable-release security policy.
- Protect release branches and require applicable project checks.
- Publish machine-readable dependency and release provenance.
- Make repository, registry, and release recovery independent of one account.

## Community and governance

- Exercise the reviewer and maintainer paths through project work.
- Record architecture, scope, and governance decisions publicly.
- Maintain bounded adopter and compatibility evidence with participant
  consent.
- Keep project and company responsibilities explicit.

## Non-goals

- Replacing the native authority of infrastructure providers and specialist
  systems.
- Requiring a private company service for the upstream runtime.
- Combining all project components into one source repository.
