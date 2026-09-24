---
description: Review current changes with the native mergeCraft reviewer subagent
agent: mergecraft/reviewer
---

Review the current change. $ARGUMENTS

!`git diff --stat && git diff && git diff --cached`

This is the native engine: no mergecraft provider tokens are spent. Use
`/mergecraft/review-deep` when you want the deterministic analyzers, the JEV
screen, and the verifier as well.
