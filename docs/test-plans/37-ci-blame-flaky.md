# CI blame, flaky classification and failure-path extraction — test plan

Wave plan: `.ignorelocal/waves/37-ci-blame-flaky-wave-plan.md`
Worktree: `../mc-blame` @ `wave/ci-blame-flaky`

Authoring wave: **BL1** (`test-creator`, RED). Implementation: **BL2** (`ci/paths.py`),
**BL3** (`ci/flaky.py`), **BL4** (`ci/blame.py`, `ci/review.py`, `ci/verification.py`,
`ci/intelligence.py`, `mcp/ci_intelligence.py`, `REVIEW-CHECKS.md`). Final: **BL5**
(`wave-verifier` → operator; the operator merges).

This doc is the contract map for the suite BL1 authors. Every new assertion is RED on
the BL1 anchor (`1ec73a1f`) for the reason named in the *RED evidence* table; every
guard listed below is a real pass on the anchor and stays green after BL2–BL4.

## No xfail markers

BL1 is the RED sub-wave of a single-branch, single-PR plan. The acceptance is a **real
failing suite** (`uv run pytest` shows the new tests failing), not an xfail-only read,
so no `strict=False` cross-wave markers are used. Each wave greens its own slice:
BL2 greens the U4/N5 path tests, BL3 the U3/N11 flaky tests, BL4 the U1/U2 blame and
end-to-end tests. Guards are green throughout.

## Locked decisions covered (BL-D1 … BL-D13)

| Decision | What the suite pins |
| --- | --- |
| **BL-D1** | `blame_failure` returns `unknown` when evidence does not decide; `probably_not_this_pr` is reserved for a positive exoneration signal |
| **BL-D2** | `unknown` → `introduced_by_pr: "unknown"` via `annotate_unattributed`, severity `Major`, not routed to the verifier, no inline comment, **blocks** the packet |
| **BL-D3** | Only a same-fingerprint base `failure` exonerates; `success` → `unknown` (base passed, this failure is new here); any other status → `unknown` naming it; compared after `.strip().lower()` |
| **BL-D4** | `caused_by_pr` still requires path overlap; base success never promotes |
| **BL-D5** | Per-cluster base evidence: a matching `base_branch_runs` entry is authoritative; the scalar `base_branch_status` applies only at exactly one cluster |
| **BL-D6** | `pre_existing` iff a matching base run concluded `failure`; base success + failing attempts → `stable`, `blame_on_author=True`; mixed base outcomes with ≥1 failure → `pre_existing` naming the failing ref |
| **BL-D7** | Every summary names which run concluded what; no "probably" inside a decided verdict |
| **BL-D8** | Extraction only from failure-context forms (`FAILED`/`ERROR` + path[`::node`], line-start `path:line:`, `path(line,col)`); root files accepted; bare `_PYTEST_NODE` removed |
| **BL-D9** | One `normalize_repo_path` applied to extracted paths **and** `pr_diff_paths`; `failure_line` accepts `./` and `(line,col)`; absolute/URL paths stay dropped |
| **BL-D10** | `CiReviewStats.unattributed_count`, payload `stats.unattributedCount`, pre-merge row "N unattributed" |
| **BL-D11** | No prompt edit; the tool description and the `unknown` summary carry the semantics |
| **BL-D12** | The four exoneration-pinning tests are inverted in BL1, never deleted |
| **BL-D13** | No coverage floor, no new required check, no provider change |

## Attribution matrix (target)

Read left to right. "Overlap" is evaluated after `normalize_repo_path` on both sides
(BL-D9). "Base" means a same-fingerprint base run (or, at exactly one cluster, the
scalar `base_branch_status`).

| Overlap | Base evidence | Verdict | Recorded as | Severity | Blocks? |
| --- | --- | --- | --- | --- | --- |
| yes | any | `caused_by_pr` | `introduced_by_pr: "true"` | `Major` | yes |
| no | base concluded `failure` | `probably_not_this_pr` | `"false"` (`annotate_not_caused_by_pr`) | `Minor` | no |
| no | `success` / `cancelled` / other / absent / >1 cluster scalar | `unknown` | `"unknown"` (`annotate_unattributed`) | `Major` | yes |
| no path extracted | base concluded `failure` | `probably_not_this_pr` (positive exoneration) | `"false"` | `Minor` | no |
| no path extracted | anything else | `unknown`, `hunk is None` | `"unknown"` | `Major` | yes |

The no-path/base-`failure` row is the tension resolution recorded below.

## Flaky matrix (target)

| Retry attempts | Matching base run(s) | Classification | `blame_on_author` |
| --- | --- | --- | --- |
| mixed (`failure` + `success`) | any | `flaky` | `False` |
| `failure` only | `failure` | `pre_existing` (summary names the ref and "failed") | `False` |
| `failure` only | `success` only | `stable` (summary names the ref and "passed") | `True` |
| `failure` only | mixed, ≥1 `failure` | `pre_existing`, naming the failing run's ref | `False` |
| `failure` only | none | `stable` | `True` |

`pre_existing` is reachable **only** through the matching-base-`failure` row; the
unreachable `ci/flaky.py:66-74` branch has no replacement.

## Tension resolution (BL-D7 vs the retired "probably not this PR" phrase)

Two tests asserted the literal phrase `"probably not this PR"` inside a **decided**
exoneration summary:

- `tests/mcp/test_ci_intelligence.py::test_analyze_ci_failures_tool_returns_review_payload`
  (listed as a guard that stays green), and
- `tests/ci/test_blame.py::test_failure_outside_diff_reports_probably_not_this_pr`
  (the unrelated fixture with scalar `base_branch_status="failure"`).

BL-D7 forbids "probably" inside a decided verdict, so the phrase cannot survive in the
summary. Resolution chosen: **option (2)** — update the literal assertions to check the
exoneration **substance**, not the word "probably".

- The MCP guard keeps its structural assertions green on the anchor and after BL4:
  `blameVerdict == "probably_not_this_pr"`, the base conclusion ("fail…") named in the
  summary, `prAttributedCount == 0`, `clusterCount == 1`, `preMergeSummary` present.
- `test_failure_outside_diff_reports_probably_not_this_pr` keeps `== "probably_not_this_pr"`
  and now also asserts the summary names the base `failure`, **does not** contain
  "probably", and that `hunk is None` (no failure-context path in the fixture).
- `tests/ci/test_review_integration.py::test_analyze_ci_failures_orchestrator_path_renders_verdict_lines`
  is updated the same way: the verdict token stays, the phrase assertion becomes
  `"probably not this pr" not in section.lower()` plus a "fail" name.

Nothing is loosened to a set membership; the discarded word is replaced by a substance
check (base conclusion named + attribution token + count), never by a vague predicate.

### No path at all, but a base `failure` **is** present

BL-D1's "no path extracted at all" branch would read as `unknown`, but a same-fingerprint
base `failure` is the *positive* exoneration signal BL-D1 reserves
`probably_not_this_pr` for. Precedence is pinned explicitly: **base `failure` exonerates
even when no path was extracted** (the fixture `blame_unrelated_to_pr.json` is exactly
this shape: no failure-context path, scalar base `failure`). The `unknown` branch applies
only when the base does **not** conclude `failure`. Encoded in
`test_blame.py::test_failure_outside_diff_reports_probably_not_this_pr` and
`test_blame.py::test_no_path_and_no_base_evidence_is_unknown_without_a_sentinel`.

## Contract → test mapping

### Unit — `ci/paths.py` (BL2; U4 / N5)

| Contract | Test | File |
| --- | --- | --- |
| `setup.py:12:` (root file, line-start citation) extracted | `test_failure_context_forms_are_extracted_and_normalised[setup.py:12: …]` | `tests/ci/test_paths.py` |
| `FAILED test_root.py::t` (root file, pytest report) extracted | `test_failure_context_forms_are_extracted_and_normalised[FAILED test_root.py::t …]` | `tests/ci/test_paths.py` |
| `src/a.ts(3,5): error` extracted | `test_failure_context_forms_are_extracted_and_normalised[src/a.ts(3,5) …]` | `tests/ci/test_paths.py` |
| `./src/a.py:3:` extracted **normalised** | `test_failure_context_forms_are_extracted_and_normalised[./src/a.py:3: …]` | `tests/ci/test_paths.py` |
| `normalize_repo_path` strips `./`, collapses `//` | `test_normalize_repo_path_strips_dot_slash_and_collapses_slashes` | `tests/ci/test_paths.py` |
| `failure_line` returns 3 for `./` and `(line,col)` | `test_failure_line_accepts_dot_slash_and_line_col_forms` | `tests/ci/test_paths.py` |
| `PASSED` / `collecting` / command echo / bare URL yield no path | `test_non_failure_lines_yield_no_failure_path[*]` | `tests/ci/test_paths.py` |
| absolute (traceback) dropped — **guard (green)** | `test_absolute_path_in_a_traceback_citation_stays_dropped` | `tests/ci/test_paths.py` |
| one FAILED node yields exactly one path | `test_flaky_retry_failure_attempt_yields_only_the_failed_path` | `tests/ci/test_paths.py` |

> The plan's "absolute and `https://` still dropped" guard is realised on the anchor by
> the **traceback** absolute form, which the extractor already drops. The
> `FAILED /home/runner/…` and `FAILED https://…` forms are pinned as **red** N5 tests,
> not guards: on the anchor the bare `_PYTEST_NODE` strips the leading `/` and keeps
> `home/runner/…`, and keeps `example.com/src/a.py` from a URL. BL-D9/BL-D8 remove that
> false positive. Recorded here so the deviation from the plan's "guard" label is
> deliberate, not a loosened assertion.

### Unit — `ci/blame.py` (BL4; U1 / U2)

| Contract | Test | File |
| --- | --- | --- |
| Overlap → `caused_by_pr` — **guard (green)** | `test_failure_touching_diff_maps_to_introducing_hunk` | `tests/ci/test_blame.py` |
| No overlap + no base → `unknown` | `test_blame_unknown_when_paths_do_not_overlap_and_base_unknown` | `tests/ci/test_blame.py` |
| No path extracted → `unknown`, `hunk is None`, no `ci/pipeline` | `test_no_path_and_no_base_evidence_is_unknown_without_a_sentinel` | `tests/ci/test_blame.py` |
| Base `failure` / `"  FAILURE "` / `"Failure"` → `probably_not_this_pr` | `test_only_a_base_failure_exonerates[failure …]` | `tests/ci/test_blame.py` |
| Base `success` / `cancelled` / `None` → `unknown` | `test_only_a_base_failure_exonerates[success/cancelled/None]` | `tests/ci/test_blame.py` |
| Base `success` summary says the base passed | `test_a_passing_base_branch_does_not_exonerate` | `tests/ci/test_blame.py` |
| Unrecognised status named in the summary | `test_an_unrecognised_base_status_does_not_exonerate` | `tests/ci/test_blame.py` |
| Base `failure` exonerates even with no path; BL-D7 summary | `test_failure_outside_diff_reports_probably_not_this_pr` | `tests/ci/test_blame.py` |
| `./` normalised on the diff side too | `test_blame_normalises_dot_slash_on_both_sides` | `tests/ci/test_blame.py` |
| A `PASSED` path never becomes `caused_by_pr` | `test_flaky_retry_log_does_not_blame_a_path_that_passed` | `tests/ci/test_blame.py` |

### Unit — `ci/flaky.py` (BL3; U3 / N11)

| Contract | Test | File |
| --- | --- | --- |
| Retry flip → `flaky` — **guard (green)** | `test_same_fingerprint_different_retry_outcomes_is_flaky` | `tests/ci/test_flaky.py` |
| Mixed retry + base failure stays `flaky` — **guard (green)** | `test_flaky_verdict_names_base_branch_not_author` | `tests/ci/test_flaky.py` |
| Base `failure` → `pre_existing`, names ref + "failed" | `test_base_branch_same_fingerprint_is_pre_existing` | `tests/ci/test_flaky.py` |
| Base `success` + failing attempts → `stable`, `blame_on_author=True`, names ref + "passed" | `test_base_success_with_failing_attempts_is_stable_and_blames_the_author` | `tests/ci/test_flaky.py` |
| `"Failure"` conclusion casing honoured | `test_matching_base_failure_conclusion_casing_is_honoured` | `tests/ci/test_flaky.py` |
| Mixed base outcomes exonerate only on the failing ref | `test_mixed_base_outcomes_exonerate_only_on_the_failing_ref` | `tests/ci/test_flaky.py` |

### Integration — clustering + MCP pipeline (BL4; U1 / U2)

| Contract | Test | File |
| --- | --- | --- |
| Per-fingerprint base runs exonerate exactly one cluster; `unattributedCount == 1` | `test_mixed_failures_cluster_and_attribute_correctly` | `tests/ci/test_ci_intelligence.py` |
| Two clusters ignore a single scalar status; both unattributed | `test_two_clusters_ignore_a_single_scalar_base_status` | `tests/ci/test_ci_intelligence.py` |
| Exactly one cluster keeps the scalar fallback; `unattributedCount == 0` | `test_single_cluster_scalar_base_status_still_applies` | `tests/ci/test_ci_intelligence.py` |
| Flaky retry surfaces in section + pre-merge row — **guard (green)** | `test_flaky_retry_surfaces_in_section_and_pre_merge_row` | `tests/ci/test_ci_intelligence.py` |
| PR-attributed failure produces an inline comment — **guard (green)** | `test_pr_attributed_failure_produces_inline_comment` | `tests/ci/test_ci_intelligence.py` |
| One cluster + scalar `failure` is exonerated (MCP tool) — **guard (green)** | `test_analyze_ci_failures_tool_returns_review_payload` | `tests/mcp/test_ci_intelligence.py` |

### Functional / E2E — review seam + packet (BL4; U1 / U2)

| Contract | Test | File |
| --- | --- | --- |
| `unknown` cluster: Major / `unknown`, `unattributed_count == 1`, "1 unattributed", no inline comment | `test_unattributed_cluster_is_counted_and_gets_no_inline_comment` | `tests/ci/test_review_integration.py` |
| Decided exoneration renders without a hedge and `unattributedCount == 0` | `test_analyze_ci_failures_orchestrator_path_renders_verdict_lines` | `tests/ci/test_review_integration.py` |
| `analyze_ci_failures` records clusters as `"unknown"` / `Major` | `test_analyze_ci_failures_records_its_clusters_as_ci_evidence` | `tests/ci/test_evidence_seams.py` |
| `annotate_unattributed` is `unknown` / `Major`, not verifier-routed | `test_unattributed_ci_finding_is_unknown_and_never_routed_to_the_verifier` | `tests/ci/test_evidence_seams.py` |
| An unattributed cluster **blocks** the packet verdict (mirror of the PR-attributed test) | `test_unattributed_ci_cluster_blocks_the_packet_verdict` | `tests/ci/test_evidence_seams.py` |
| Flaky CI finding does not flip the packet — **guard (green)** | `test_flaky_ci_finding_does_not_flip_the_packet_verdict` | `tests/ci/test_evidence_seams.py` |
| PR-attributed CI finding blocks the packet — **guard (green)** | `test_pr_attributed_ci_finding_does_block_the_packet_verdict` | `tests/ci/test_evidence_seams.py` |
| Flaky CI finding never blocks the approval gate — **guard (green)** | `test_flaky_ci_finding_never_blocks_the_approval_gate` | `tests/ci/test_evidence.py` |

## RED evidence (anchor `1ec73a1f`)

`MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/ci/test_paths.py tests/ci/test_blame.py
tests/ci/test_flaky.py tests/ci/test_ci_intelligence.py tests/ci/test_review_integration.py
tests/ci/test_evidence_seams.py tests/ci/test_evidence.py tests/mcp/test_ci_intelligence.py -q`
→ **36 failed, 50 passed**; all 36 failures are the intended REDs, zero collection
errors.

| Test | Why it fails on the anchor |
| --- | --- |
| `test_paths.py::test_failure_context_forms_are_extracted_and_normalised[setup.py / FAILED test_root.py / src/a.ts(3,5)]` | `_REPO_PATH` requires a directory segment, so root files and `(line,col)` yield `[]` |
| `…[…/./src/a.py:3:]` | extracted as `./src/a.py`, not normalised |
| `test_paths.py::test_normalize_repo_path_strips_dot_slash_and_collapses_slashes` | `normalize_repo_path` does not exist (`AttributeError`) |
| `test_paths.py::test_failure_line_accepts_dot_slash_and_line_col_forms` | `failure_line` returns `1` for both forms |
| `test_paths.py::test_non_failure_lines_yield_no_failure_path[*]` | bare `_PYTEST_NODE` matches any path-shaped token: `PASSED`, `collecting`, `uv run …`, a bare URL, and `FAILED /home/…` / `FAILED https://…` |
| `test_paths.py::test_flaky_retry_failure_attempt_yields_only_the_failed_path` | the attempt yields seven paths, six from `PASSED` lines |
| `test_blame.py::test_blame_unknown_when_paths_do_not_overlap_and_base_unknown` | returns `probably_not_this_pr` (declared `unknown` never returned) |
| `test_blame.py::test_no_path_and_no_base_evidence_is_unknown_without_a_sentinel` | `primary_failure_path` fabricates `ci/pipeline`; `hunk` is not `None` |
| `test_blame.py::test_only_a_base_failure_exonerates[success/cancelled/None]` | any truthy status exonerates |
| `test_blame.py::test_a_passing_base_branch_does_not_exonerate` | base `success` → `probably_not_this_pr` |
| `test_blame.py::test_an_unrecognised_base_status_does_not_exonerate` | base `cancelled` → `probably_not_this_pr` |
| `test_blame.py::test_failure_outside_diff_reports_probably_not_this_pr` | summary hedges "probably", `hunk` not `None` |
| `test_blame.py::test_blame_normalises_dot_slash_on_both_sides` | diff `./src/a.py` never matches `src/a.py` |
| `test_blame.py::test_flaky_retry_log_does_not_blame_a_path_that_passed` | a `PASSED` path overlaps the diff → `caused_by_pr` |
| `test_flaky.py::test_base_branch_same_fingerprint_is_pre_existing` | headline says "already fails" (N11) |
| `test_flaky.py::test_base_success_with_failing_attempts_is_stable_and_blames_the_author` | a matching base (any conclusion) + a failing attempt → `pre_existing` |
| `test_flaky.py::test_matching_base_failure_conclusion_casing_is_honoured` | headline contradicts the evidence |
| `test_flaky.py::test_mixed_base_outcomes_exonerate_only_on_the_failing_ref` | names the first matching ref, not the failing one |
| `test_ci_intelligence.py::test_mixed_failures_cluster_and_attribute_correctly` | `base_branch_runs` ignored; `stats.unattributedCount` absent |
| `test_ci_intelligence.py::test_two_clusters_ignore_a_single_scalar_base_status` | one scalar exonerates both clusters; `unattributedCount` absent |
| `test_ci_intelligence.py::test_single_cluster_scalar_base_status_still_applies` | `unattributedCount` absent |
| `test_review_integration.py::test_unattributed_cluster_is_counted_and_gets_no_inline_comment` | blame returns `probably_not_this_pr`; `CiReviewStats` has no `unattributed_count` |
| `test_review_integration.py::test_analyze_ci_failures_orchestrator_path_renders_verdict_lines` | the section still contains "probably not this pr" |
| `test_evidence_seams.py::test_analyze_ci_failures_records_its_clusters_as_ci_evidence` | records `"false"` / `Minor` instead of `"unknown"` / `Major` |
| `test_evidence_seams.py::test_unattributed_ci_finding_is_unknown_and_never_routed_to_the_verifier` | `annotate_unattributed` does not exist |
| `test_evidence_seams.py::test_unattributed_ci_cluster_blocks_the_packet_verdict` | the cluster records `Minor`, so the packet does not block |
| `test_evidence_seams.py::test_recorded_finding_count_is_merged_evidence_length` | `CiReviewStats` rejects the new `unattributed_count` field |

## Acceptance (plan §BL1)

36 collected-and-red as above; all guards green; zero collection errors; `make lint` +
`make typecheck` clean. Post-BL2/BL3/BL4: each wave greens its slice, and BL5 runs the
scoped suite plus `make ci-static`. Live gates: none in BL1 — `skipped: no live gate`.
