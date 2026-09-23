---
description: Build the mergeCraft review prompt without invoking a model
agent: build
---

Materialize the review prompt for the current change without spending tokens.
$ARGUMENTS

```bash
mergecraft review --dry-run
```

Report what the run would have reviewed: the changed paths, the analyzers that
would run, the resolved model chain, and any config problems `--dry-run`
surfaces. This is the cheap way to debug a review that is misbehaving.
