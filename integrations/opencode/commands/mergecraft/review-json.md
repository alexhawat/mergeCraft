---
description: Review current changes and write machine-readable findings to disk
agent: build
---

Review the current change and persist structured findings. $ARGUMENTS

```bash
mergecraft review --json mergecraft-findings.json
```

Then read `mergecraft-findings.json`, summarize findings grouped by severity with
`file:line` anchors, and state how many are blocking. Do not commit the JSON file
unless the user asks; add it to `.gitignore` if it will be regenerated.
