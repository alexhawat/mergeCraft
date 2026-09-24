---
description: Fast mergeCraft review — deterministic analyzers only, no LLM call
agent: build
---

Run only the deterministic analyzers over the current change. $ARGUMENTS

```bash
mergecraft analyzers detect       # which analyzers apply to the changed paths
mergecraft analyzers run <id>     # run one against the working tree
mergecraft analyzers list         # catalog and enablement
```

This engine makes no model call, so it is safe to run often and in tight loops.
It is a narrowing step, not a substitute for `/mergecraft/review` — report it as
"analyzers only" so nobody mistakes it for a full verdict.
