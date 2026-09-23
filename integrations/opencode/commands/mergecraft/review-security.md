---
description: Security-focused review of current changes
agent: mergecraft/reviewer
---

Review the current change for security only. Ignore style and ordinary
correctness unless it creates a security consequence. $ARGUMENTS

Look specifically for: weakened authorization, injection (command, SQL, path,
template), secrets in the diff, trust-boundary crossings, unsafe deserialization,
and fail-open error handling.

!`git diff --stat && git diff && git diff --cached`

For a deeper, evidence-backed pass, run `/mergecraft/review-deep` and then
`mergecraft lens show security` to see the repo's security lens rubric.
