---
description: Apply mergeCraft findings and re-review (review-only loop)
agent: mergecraft/fixer
---

Apply the open mergeCraft findings to the working tree, then re-review. $ARGUMENTS

Follow the fixer loop: read the most recent findings, fix the most severe one in
the smallest way, run `mergecraft review --agent` on the updated change, and stop
on the verdict / exit code. If re-review cannot run, report the fixes and mark
the loop inconclusive — never claim the change is clean.
