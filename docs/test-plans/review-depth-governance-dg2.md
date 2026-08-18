# PR DG2 — large-PR engine and finding lifecycle — test plan (DG2.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG2)
Worktree: `../mergecraft-dg2-large-pr` @ `wave/dg2-large-pr` (based on DG1 @ c638a1f)
Authoring wave: **DG2.1** (tests-first). Implementation: **DG2.2**.
xfail-reconciliation: **post-DG2.2** (complete).

Locked decisions: **convention 3** (review-only — split advice is text), file 2
**D12** (reduced scope is reported, never silent).

## xfail schedule

Ten DG2.1 tests use `@pytest.mark.xfail(reason="green after DG2.2",
strict=False)`. One regression pin passes today.

| Test file | Tests | Marker | Status pre-DG2.2 |
|-----------|-------|--------|------------------|
| `tests/classify/test_change_clustering.py` | 2 | xfail | **RED** |
| `tests/review/test_hierarchical_summaries.py` | 3 | xfail | **RED** |
| `tests/findings/test_lifecycle.py` | 3 + 1 pin | xfail / none | **1 PASS, 3 RED** |
| `tests/review/test_split_advisor.py` | 2 | xfail | **RED** |

**Acceptance (DG2.1):** 11 collected; 1 pass; 10 xfail. `make lint` + `make typecheck`
clean.

## Target API DG2.2 must satisfy

### `src/mergecraft/classify/change_clustering.py` (new)

| Symbol | Contract |
|--------|----------|
| `cluster_changes(change, *, dependency_edges, intents)` | Group changed paths by dependency edges and declared intent; expose `clusters` and `independent_groups` for the split advisor. |

### `src/mergecraft/review/hierarchical_summaries.py` (new)

| Symbol | Contract |
|--------|----------|
| `build_hierarchical_context(diff_text, *, token_budget, risk_regions)` | Large diff → map + cluster summaries + raw hunks; `token_estimate` respects budget; high-risk paths keep verbatim hunks; `scope_reduction` is a `ScopeReduction` when scope is omitted (D12). |

### `src/mergecraft/findings/lifecycle.py` (new)

| Symbol | Contract |
|--------|----------|
| `dispute_finding(fingerprint, *, reason)` | Record `disputed` with reason (G7). |
| `waive_finding(fingerprint, *, reason, expires_at)` | Record `waived` with reason and expiry. |
| `lifecycle_state(record)` | Return canonical state string. |
| `lifecycle_state_from_thread(thread)` | Map thread dict to `open` / `resolved-by-change` / `stale` / `disputed` / `waived`; must not break `findings/threads.py` normalization (regression pin). |

Regression pin: `fetch_review_threads` + `carryover_findings` behavior for
resolved/outdated threads (`test_resolved_by_change_still_works`).

### `src/mergecraft/review/split_advisor.py` (new)

| Symbol | Contract |
|--------|----------|
| `recommend_pr_split(independent_groups, *, output_path=None)` | When groups are unrelated, recommend ≥2 PRs with paths and summary text; `advisory_only=True`; never write `output_path` (convention 3). |

## Contract → coverage matrix

### Change clustering — `tests/classify/test_change_clustering.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_files_cluster_by_dependency_and_intent` | unit | happy | Dependency + intent clustering |
| 2 | `test_independent_groups_are_identified` | unit | split input | Unrelated groups surfaced |

### Hierarchical summaries — `tests/review/test_hierarchical_summaries.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 3 | `test_large_diff_reduces_to_map_then_summaries_then_hunks` | integration | happy | Map → summaries → hunks pipeline |
| 4 | `test_high_risk_regions_keep_raw_tokens` | unit | edge | Risk paths keep raw hunks |
| 5 | `test_reduced_scope_is_reported` | unit | D12 | Explicit `ScopeReduction` |

### Finding lifecycle — `tests/findings/test_lifecycle.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 6 | `test_disputed_state_is_recorded` | unit | happy | G7 disputed + reason |
| 7 | `test_waived_state_carries_reason_and_expiry` | unit | edge | Waived + expiry |
| 8 | `test_resolved_by_change_still_works` | regression | pin | `threads.py` + carryover |
| 9 | `test_stale_finding_is_distinguishable_from_resolved` | unit | edge | stale ≠ resolved-by-change |

### Split advisor — `tests/review/test_split_advisor.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 10 | `test_unrelated_groups_produce_a_split_recommendation` | functional | happy | Split recommendation text |
| 11 | `test_split_advice_is_advisory_only` | functional | convention 3 | No repo writes |

## Imports of not-yet-existing symbols

DG2.2 modules are imported **inside test bodies** (or via local helpers) so
collection stays clean before implementation lands.

## Status

DG2.1 RED suite committed 2026-08-18 @ `015d9d9` — 11 collected, 1 pass, 10 xfail.
Awaiting DG2.2 implementation and xfail reconciliation.
