---
name: merge-attention
description: Apply the mergeCraft merge-attention rubric to a diff or evidence packet without a full Action run. Use when the user wants the same low/medium/high grade locally as CI publishes.
compatibility: Requires mergecraft-action package from this repository
---

# Merge-attention lens

This optional skill mirrors the Action's merge-attention rubric (`docs/merge-attention.md`). It is **additive** — it does not replace `mergecraft review` or change merge gates.

## Prerequisites

Install the mergeCraft CLI from the [matching release docs](https://github.com/alexhawat/mergeCraft/tree/v0.1.0a7/docs):

```bash
uv tool install mergecraft-action==0.1.0a7
```

## Install

Copy this directory to your agent skills path, for example:

```bash
mkdir -p .agents/skills/merge-attention
cp -r skills/merge-attention/* .agents/skills/merge-attention/
```

## Use on a completed run

After `mergecraft review --evidence-packet /tmp/packet.json`:

```python
from mergecraft.evidence.packet import MergeEvidencePacket
from mergecraft.merge_attention.compose import compose_merge_attention
from mergecraft.merge_attention.render import merge_attention_summary_block

packet = MergeEvidencePacket.model_validate_json(open("/tmp/packet.json").read())
section = compose_merge_attention(packet)
print(merge_attention_summary_block(section))
```

## Example output (sample diff)

For a single-file doc change with low blast radius and no blockers:

```markdown
### Merge-attention grade

**Overall:** `low` — human-attention heuristic only; does not gate merge.

| Axis | Grade | Verdict |
| --- | --- | --- |
| Alignment | `low` | No scope-drift or fix-proof lane reasons; alignment looks consistent with evidence. |
| Impact / blast radius | `low` | Blast-radius lane is `low` (baseline.clean). |
| Verification | `low` | Deterministic analyzers ran on this change. |
| Rollback cost | `low` | Rollback cost tracks blast-radius lane; no rollback policy evidence was required. |
| Error detection | `low` | Error-detection posture follows blast-radius; no health-check evidence required. |
```

For a UI change without screenshots in the PR body or run evidence directory, expect **verification** `medium` or `high` with an explicit verification-gap sentence.

## Thresholds

Same as the Action: overall = max(axis levels); uncalibrated; no per-finding numeric confidence.