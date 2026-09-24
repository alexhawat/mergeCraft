---
description: Review a pull request by number with mergeCraft
agent: build
---

Review pull request $1. $ARGUMENTS

**Validate first.** The argument must be a positive integer PR number. If `$1`
is empty or contains anything other than digits, stop and ask for a number —
never run a command that interpolates it.

Review the PR head ref directly; no checkout is needed:

```bash
mergecraft review \
  --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)" \
  --head "pull/$1/head" \
  --base "$(gh pr view "$1" --json baseRefName -q .baseRefName)"
```

`mergecraft review` reads the diff only and never posts PR comments. If you
prefer a local checkout instead, `gh pr checkout "$1"` first, then
`mergecraft review --base "origin/$(gh pr view "$1" --json baseRefName -q .baseRefName)"`.

Then summarize findings grouped by severity with `file:line` anchors.
