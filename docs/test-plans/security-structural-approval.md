# Security — structural approval gate (#75) — test plan (W7 RED → W8 GREEN)

Wave plan: `.ignorelocal/waves/issues-security-trust-boundary-wave-plan.md`
Worktree: `mergecraft-sec-d-structural-gate` @ `wave/sec-d-structural-gate`

## xfail schedule

All W7 xfail markers were removed at W8. The 15 tests in
`tests/status_checks/` now pass on the structural-approval gate (`make
ci` green, 623 passed; the status_checks subtree is 15 / 15).

The in-repo regression guard
`test_in_repo_pr_with_pr_approve_enabled_can_self_approve` already passed
pre-W8 (the prior code did send `event="APPROVE"` for trusted runs); it
was marked xfail only to keep the W7 cycle consistent and is now plain.

The pre-W8
`tests/utils/test_status_checks.py::test_report_status_checks_preserves_approval_when_run_fails_later`
was renamed to `test_report_status_checks_neutral_for_crashed_run_with_recorded_approval`
and rewritten to assert the W8 / D13 contract: a recorded
`ApprovalRecord(would_approve=False)` does not flip a crashed run to
`failure` — the conclusion is `neutral` regardless, and the reviewed
commit SHA is preserved in the summary so operators can audit the run.

No non-xfail collection tests guard this suite. The conftest does a
`import mergecraft.analyzers.finding` and
`import mergecraft.utils.status_checks` at module load so a missing
module is a hard collection failure rather than a deferred runtime
error.

## Contract matrix

Per D12, D13, D14 of the wave plan. The test names below map to W7.1–W7.6
in the plan.

| Plan W | Decision | Layer | Scenario | Primary test |
|--------|----------|-------|----------|--------------|
| **W7.1** | D12 — conclusion is a pure function of `Finding` severities, never narrative | Decision | Headline acceptance: narrative says "approved" + blocker finding ⇒ `failure` | `test_narrative_approval_with_blocker_finding_yields_failure` |
| **W7.2** | D12 — same findings, three different narratives ⇒ identical conclusion | Decision | Purity / no-I/O | `test_approval_conclusion_is_pure_function_of_findings` (parametrized: approve / block / unrecorded) |
| **W7.3** | D13 — fail closed on incomplete runs; `neutral` is the wire-shape the hardened enforce step blocks on | Enforce | `run_succeeded=False` ⇒ non-`success`; crashed-run through `report_status_checks` ⇒ `neutral` | `test_crashed_run_does_not_leave_permissive_gate`, `test_timed_out_run_with_findings_yields_failure`, `test_report_status_checks_surfaces_neutral_for_crashed_run` |
| **W7.4** | D14 — untrusted (fork / `pull_request_target`) runs cannot self-approve | Decision + tool | `derive_trust_tier()` returns `"untrusted"` ⇒ decision is non-`success`; `create_pull_request_review` does not send `event="APPROVE"` even with `pr_approve_enabled=True` and `approved=True`. Regression guard: in-repo PR still approves. | `test_fork_pr_cannot_self_approve_at_decision_layer`, `test_fork_pr_cannot_self_approve_at_tool_layer`, `test_in_repo_pr_with_pr_approve_enabled_can_self_approve` |
| **W7.5** | D12 — agent's `approved` boolean is advisory only | Decision | `create_pull_request_review(approved=True)` with no findings ⇒ `neutral` (not `success`); with a blocker ⇒ `failure`; `ApprovalRecord.would_approve=True` does not by itself produce `success` | `test_agent_approved_flag_is_advisory_only_with_empty_findings`, `test_agent_approved_flag_is_advisory_only_with_blocking_findings`, `test_approval_record_remains_an_advisory_input` |
| **W7.6** | D12 — no parallel finding model | Structural | The decision function imports `Finding` from `analyzers/finding.py`; no class with `Finding` suffix lives in `mergecraft.agents.gates`; `decide_approval`'s `findings` argument is annotated `list[Finding]`; `Finding.source` is preserved across the call (merge-evidence plan #41/#46 reconstruct the conclusion from stored findings) | `test_no_second_finding_model_introduced`, `test_finding_source_is_preserved_for_evidence_audit` |

## Fixture model

The conftest in `tests/status_checks/conftest.py` exposes typed findings
at three severity tiers — `blocker_finding` (Major), `critical_finding`
(Critical), `trivial_finding` (Trivial) — plus three composed lists
(`sample_findings`, `blocker_only_findings`, `clean_findings`,
`clean_findings_with_trivial`). All findings use
`FindingSource = "agent"` so the structural-guard test (W7.6) sees a
single source across the suite.

`blocked_pr_event` and `trusted_pr_event` are raw GitHub event
dicts shaped the way `derive_trust_tier()` expects — a fork PR (head
repo `fork: True`) and an in-repo PR (head repo `fork: False`).

The conftest also imports `mergecraft.analyzers.finding.Finding` and
`mergecraft.utils.status_checks.{Conclusion, report_status_checks}` at
module load so a missing import is a hard collection failure rather
than a deferred test fixture error.

## What W8 satisfies (D12, D13, D14)

The decision function lands in `src/mergecraft/agents/gates.py` (W8.1)
with this contract:

```python
def decide_approval(
    findings: list[Finding],
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> Conclusion: ...
```

- `Findings = []` + `run_succeeded=True` + `tier="trusted"` ⇒ `"neutral"`
  (the hardened enforce step blocks on `neutral` — D13).
- `Findings = []` + `run_succeeded=False` ⇒ `"neutral"` (D13).
- Any `Critical` or `Major` finding ⇒ `"failure"` regardless of run
  state (D12).
- `tier="untrusted"` ⇒ never `"success"` and never `"neutral"` with
  blocker prerequisites; the gate is inert for fork PRs and
  `pull_request_target` regardless of `pr_approve_enabled` (D14).
- `tier="trusted"` + no blockers + `run_succeeded=True` + at least one
  non-blocker finding ⇒ `"success"`.

`report_status_checks()` (W8.2) calls `decide_approval()` instead
of reading `approval.would_approve` directly. The agent's boolean stays
in `ApprovalRecord.would_approve` (W8.3) as an advisory input the
trajectory/evidence work in the merge-evidence plan reads after the
fact (#41).

`create_pull_request_review` (W8.5) does not send `event="APPROVE"` to
GitHub when `ctx.trust_tier == "untrusted"`, even with
`pr_approve_enabled=True` and `approved=True`. The advisory record
(`ApprovalRecord(would_approve=True, sha=...)`) is still stored — the
guard is at the wire-call layer, not the storage layer.

W8.6 emits the decision inputs (findings count, severities present,
`run_succeeded`, `tier`, `has_blocker`) into the check-run summary so
the conclusion is reconstructible from the stored findings alone (#75
proposal item 4). The full durable artifact lives in the merge-evidence
plan's `MergeEvidencePacket` (#47); W8 does not introduce a second
packet format.

## Cross-file pins

This plan is the **first** of the merge-evidence-gating plan's
Batch-D sibling plan to land `decide_approval()`. The merge-evidence
plan's W2 (#41 evidence-not-confidence) and W9 (#46 gate→action map)
both consume `decide_approval()` rather than reimplementing it. W8 owns
the function and the `report_status_checks()` rewire; both downstream
plans rebase.

`derive_trust_tier()` (`src/mergecraft/analyzers/trust.py:30-58`) is
read-only for this plan. The analyze-evidence plan owns the signature.

`Finding` (`src/mergecraft/analyzers/finding.py:32-53`) is consumed,
not modified. W7.6's structural guard fails if W8 introduces a
parallel model.

## Out of scope for W8

- The merge-evidence plan's W2/W9 (they rebase onto this branch).
- The `examples/workflows/mergecraft.yml` minimal template (unchanged
  by W8; only the hardened template's enforce step moved).
- The merge-evidence plan's `MergeEvidencePacket` durable artifact.
- Any change to `derive_trust_tier()` itself (analyzer plan owns it).
- Any extension of `Finding` (merge-evidence plan owns it, additively).
