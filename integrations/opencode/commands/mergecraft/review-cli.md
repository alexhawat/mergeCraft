---
description: Review current changes through the mergecraft CLI (JSONL findings)
agent: build
---

Run the mergecraft CLI review engine over the current change. $ARGUMENTS

```bash
mergecraft review --agent
```

`--agent` streams JSONL events on stdout: `run_started`, `phase`, `finding`,
`verdict`, `run_finished`. Parse each `finding` line as it arrives, before the
`verdict` line. Do not redirect stdout away from the stream; human-readable text
is on stderr.

Branch on the process exit code, not on prose: `0` clean, `10` findings, `11`
blocked, `12` failed, `20` inconclusive, `30` configuration, `40` infra, `50`
timeout.

If the CLI is not installed, say so and suggest `/mergecraft/review` (native) or
`/mergecraft/setup` instead of guessing.
