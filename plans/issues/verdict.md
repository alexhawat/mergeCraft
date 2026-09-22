## Verified defect
Audited main `be9993367386b03f982c795ceb1d80e4a0bfcf1d` on 2026-09-22.

[`submit_review_verdict_tool`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/mcp/verdict.py#L943) calls `prepare_terminal_submission` before precision normalization. [The preparation helper](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/review/terminal_submission.py#L88) upgrades an approve verdict to request_changes for any raw Major/Critical finding. Lines 971-981 then downgrade findings through the precision pipeline without recomputing that verdict. [Publication](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/mcp/review.py#L989) turns the recorded verdict into GitHub REQUEST_CHANGES.

## Reproduction
Call the real preparation and normalization functions in their production order with requested verdict `approve` and:
```json
{"path":"README.md","line":1,"body":"README spelling typo","severity":"Major"}
```
Observed:
```
requested=approve
normalized_severity=Trivial
recorded_verdict=request_changes
validate_submission.accepted=True
```
Thus a nonblocking spelling finding can force a blocking GitHub review, contrary to the canonical severity policy. The approval check can disagree with the review event.

## Acceptance
- Compute automatically enforced verdicts from finalized normalized findings and current authoritative verification state, using the shared blocker policy.
- Do not erase an explicit, valid caller request_changes merely by recomputing a generated verdict; distinguish requested and automatically enforced verdicts.
- Add real MCP submission/publication tests for downgraded style/docs findings, unchanged genuine Major findings, multi-reviewer merges, and findings removed by memory/verification.
- Preserve scope, trust, missing-evidence and idempotency protections.

Priority P1; effort M; fix risk medium. Implementation plan: `plans/002-normalized-terminal-verdict.md`.
