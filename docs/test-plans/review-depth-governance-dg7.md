# Review depth governance DG7 — test plan

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG7)
Worktree: `../mergecraft-dg7-memory-feedback` @ `wave/dg7-memory-feedback`
Authoring wave: **DG7.1** (tests-first — this file). Implementation: **DG7.2**.
xfail-reconciliation: **post-DG7.2** (remove `green after DG7.2` markers).

DG7 closes G14: feedback beyond withdrawal-only capture, bounded negative memory
with an audit trail, TTL/recency weighting, contradiction detection, and lifecycle
CLI verbs. Proposed learnings remain quarantined unless `autopromoteLearnings` is
explicitly enabled (regression pin on existing D10 behaviour).

Target API (DG7.2):

- `mergecraft.utils.memory` — feedback ledger, negative-memory store, staleness helpers
- `mergecraft.cli.memory_cmd` — `mergecraft memory list|show|forget|export|import`
- Extensions to `mergecraft.utils.learnings` wiring memory into review runs

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **DG7.2** | `test_accepted_dismissed_disputed_are_recorded_with_reason` | `green after DG7.2: finding feedback capture` | pending |
| **DG7.2** | `test_feedback_is_keyed_by_fingerprint` | `green after DG7.2: feedback keyed by fingerprint` | pending |
| **DG7.2** | `test_do_not_flag_x_when_y_is_stored` | `green after DG7.2: negative memory rules` | pending |
| **DG7.2** | `test_negative_memory_is_bounded_and_auditable` | `green after DG7.2: negative memory audit trail` | pending |
| **DG7.2** | `test_over_suppression_is_detectable` | `green after DG7.2: over-suppression detection` | pending |
| **DG7.2** | `test_ttl_and_recency_weighting_apply` | `green after DG7.2: TTL and recency weighting` | pending |
| **DG7.2** | `test_contradicting_memories_are_flagged` | `green after DG7.2: contradicting memory detection` | pending |
| **DG7.2** | `test_list_show_forget_export_import` | `green after DG7.2: memory lifecycle CLI` | pending |

`test_proposed_memory_requires_activation` has **no** xfail — regression pin on
`route_learnings_for_persist(..., autopromote=False)` / `autopromoteLearnings`.

## Contract matrix

| # | Decision / convention | Layer | Scenario | Primary test |
|---|----------------------|-------|----------|--------------|
| DG7.1a | G14 — accepted/dismissed/disputed + reason | unit | three outcomes persist reason | `test_accepted_dismissed_disputed_are_recorded_with_reason` |
| DG7.1b | G14 — fingerprint key | unit | update + lookup by fingerprint | `test_feedback_is_keyed_by_fingerprint` |
| DG7.1c | negative memory rule | unit | suppress X when Y holds | `test_do_not_flag_x_when_y_is_stored` |
| DG7.1d | convention 7 — bounded + auditable | unit | cap + audit trail on suppression | `test_negative_memory_is_bounded_and_auditable` |
| DG7.1e | convention 7 — over-suppression visible | unit | high suppression ratio flagged | `test_over_suppression_is_detectable` |
| DG7.1f | TTL + recency | unit | expired dropped; recent weighted higher | `test_ttl_and_recency_weighting_apply` |
| DG7.1g | contradictions | unit | conflicting rules surfaced | `test_contradicting_memories_are_flagged` |
| DG7.1h | lifecycle CLI | functional | list/show/forget/export/import round-trip | `test_list_show_forget_export_import` |
| DG7.1i | D10 autopromote default | unit | staging unless opt-in | `test_proposed_memory_requires_activation` |

## Acceptance (DG7.1)

- 9 collected; 1 pass; 8 RED (`strict=False` xfails)
- `make lint` + `make typecheck` clean on the new tests
