---
description: Review a pull request by number with mergeCraft
agent: build
---

Review pull request #$1. $ARGUMENTS

```bash
gh pr diff $1
mergecraft review --base "origin/$(gh pr view $1 --json baseRefName -q .baseRefName)" --head "refs/pull/$1/head"
```

If `$1` is empty, list open pull requests (`gh pr list`) and ask which one to
review. Then summarize findings grouped by severity with `file:line` anchors.
