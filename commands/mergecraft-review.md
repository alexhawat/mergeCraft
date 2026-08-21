---
description: Run a local mergeCraft review of the current changes
---

Run **`mergecraft review`** against the current uncommitted and branch changes
(vs the default base branch). Summarize findings grouped by severity
(Critical/Major/Minor), quote each finding's file:line anchor, and propose fixes.

If I only want to inspect the prompt without an LLM call, use
`mergecraft review --dry-run`.

Do not use `diff-review` — it is a deprecated alias for `mergecraft review`.
