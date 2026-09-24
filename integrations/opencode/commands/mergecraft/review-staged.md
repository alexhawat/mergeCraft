---
description: Review only the staged changes with the native reviewer
agent: mergecraft/reviewer
---

Review only the staged change. Ignore unstaged edits and untracked files.
$ARGUMENTS

!`git diff --cached --stat && git diff --cached`
