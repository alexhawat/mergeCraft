---
description: Review current changes with mergeCraft (native reviewer by default)
agent: mergecraft/reviewer
---

Review the current change for correctness, security, compatibility, reliability,
performance, and test gaps. $ARGUMENTS

Criteria: use the mergecraft MCP `get_policy` and `get_capabilities` tools when
they are connected; otherwise read `REVIEW-CHECKS.md` at the repository root when
it exists.

Working tree and staged changes:

!`git diff --stat && git diff && git diff --cached`

Report findings grouped by severity with a `file:line` anchor and evidence for
each, then exactly one verdict: `approve` or `request_changes`.

Other engines: `/mergecraft/review-cli` (JSONL), `/mergecraft/review-deep`
(analyzers + verifier + evidence), `/mergecraft/review-mcp` (public MCP),
`/mergecraft/review-quick` (analyzers only), `/mergecraft/review-thirdparty`
(pin a third-party gateway).
