---
description: Enable or inspect the JEV screening gate
agent: build
---

Configure or inspect JEV (TypeSafe System One), mergeCraft's pre-LLM screening
gate. $ARGUMENTS

```bash
mergecraft jev status
mergecraft jev enable     # prompts for TYPESAFE_API_KEY when unset
mergecraft jev disable
mergecraft jev set <key> <value>
```

JEV ranks and annotates units before the generative reviewer. It is a **shadow**
gate today: `predict_jev_action` returns `enforced=False`, so it never withholds a
unit from the reviewer and never blocks a merge. Say so if anyone asks whether it
can gate a merge on its own.

Never paste a `TYPESAFE_API_KEY` into a file or a prompt; `mergecraft jev enable`
prompts for it and writes it to the local `.env`.
