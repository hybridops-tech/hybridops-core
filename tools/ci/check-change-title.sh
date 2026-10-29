#!/usr/bin/env bash
# purpose: Validate the change title recorded in repository history.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

title="${1:-}"
if [[ -z "${title}" ]]; then
  title="$(git log -1 --format=%s)"
fi

if (( ${#title} > 72 )); then
  echo "ERR: change title exceeds 72 characters" >&2
  exit 1
fi

pattern='^(build|chore|ci|docs|feat|fix|perf|refactor|release|revert|style|test)(\([a-z0-9][a-z0-9._/-]*\))?: [[:alnum:]][[:print:]]*$'
if [[ ! "${title}" =~ ${pattern} ]]; then
  echo "ERR: change title must use: type(optional-scope): concrete outcome" >&2
  exit 1
fi

detail="${title#*: }"
detail="${detail,,}"
case "${detail}" in
  update|updates|fix|changes|cleanup|"add files via upload")
    echo "ERR: change title must identify the concrete outcome" >&2
    exit 1
    ;;
esac
