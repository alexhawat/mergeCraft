---
description: Deep mergeCraft review — analyzers, LLM reviewer, verifier, evidence
agent: build
---

Run the full mergecraft engine over the current change. $ARGUMENTS

```bash
mergecraft review
```

This engine runs the deterministic analyzers first, then the JEV screen, then the
generative reviewer, then the read-only verifier on Critical/Major findings. It is
the highest-signal engine and the one to use when a change is high-stakes.

After the run:

1. `mergecraft findings export --pr <n>` for the findings a merge would bury
   (omit `--pr` for a local run).
2. `mergecraft explain` a finding that looks wrong.
3. `mergecraft evidence show <finding-id>` to inspect the evidence packet.

JEV is a shadow ranker: it never withholds a unit from the reviewer. Logfire
receives the run's spans when a Logfire token is configured.

If the CLI is missing, fall back to `/mergecraft/review` and say which engine ran.
