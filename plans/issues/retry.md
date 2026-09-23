## Verified defect
Audited main `be9993367386b03f982c795ceb1d80e4a0bfcf1d` on 2026-09-22.

[`_publish_github_review`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/mcp/review.py#L1152) sets `terminal_publication_failed=True` on an exhausted publication attempt. A later successful retry stores the review at lines 1169-1180 but never clears that flag. [Outcome classification](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/main_outcome.py#L125) then returns inconclusive with a never-published reason even though a real review receipt exists.

## Verification
An isolated Make-driven behavioral probe exercised the actual create_pull_request_review tool flow with a fake SCM response: first call raises a transient API exception, second returns review id 77. The second call succeeds and state.review.id is 77, while terminal_publication_failed remains true. Calling the real outcome classifier returns inconclusive. No GitHub write occurred.

## Acceptance
- Clear unresolved publication failure only after a valid successful publication receipt is recorded for the bound PR/head/submission.
- Preserve the failed-attempt history as diagnostics, separate from final publication status.
- Test fail→success, fail→fail, success→idempotent replay and wrong-head receipts; success must restore the correct final outcome without extra reviews.
- Keep fail-closed behavior when no successful receipt exists, including shadow-path consistency.

Priority P2; effort S; fix risk low/medium. Implementation plan: `plans/004-publication-retry-state.md`.
