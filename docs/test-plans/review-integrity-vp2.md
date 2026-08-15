# Review integrity VP2 — fail-closed terminal verdict — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md`
Worktree: `mergecraft-vp2-fail-closed` @ `wave/vp2-fail-closed` (stacked on VP1 `08cb957`)

## xfail schedule

| Wave | Test files | Marker |
|------|------------|--------|
| **VP2.2** | `tests/review/test_terminal_verdict_policy.py` (16 of 20) | *(markers removed 2026-08-16 after VP2.2)* |
| **VP2.2** | `tests/review/test_post_run_terminal_gate.py` (both) | *(markers removed 2026-08-16 after VP2.2)* |
| **VP2.3** | `tests/review/test_terminal_verdict_policy.py::test_approve_after_failed_run_static_checks_tool_is_rejected` | *(marker removed 2026-08-16 after VP2.3 persist)* |
| **VP2.4** | `tests/review/test_terminal_verdict_policy.py::test_failed_static_check_survives_empty_plan_rerun` | `@pytest.mark.xfail(reason="green after VP2.4: sticky failed static_checks", strict=False)` |

Never `strict=True` — a strict xfail that XPASSes after VP2.2 is a hard failure the impl wave cannot touch.

### Pins that must pass against current code (do not xfail)

| Test | Why it is green today |
|------|------------------------|
| `test_verifier_dropped_finding_does_not_block_approval` | Real `decide_approval` — a Trivial-only list is not `"failure"`; including the dropped Critical still is (guard-deletion pin). Signature unchanged (convention 4). |
| `test_verifier_confirmed_finding_blocks_approval` | Real `decide_approval` — a Critical finding is `"failure"`. Narrative is not a parameter. |
| `test_publication_cannot_bypass_structural_policy` | `create_pull_request_review(approved=True)` still writes `ApprovalRecord`; `decide_approval` still returns `"failure"` for a blocker. |
| `test_existing_review_and_comment_behaviour_unchanged` | Fingerprinted inline comments, same-SHA replay skip, `create_issue_comment`, `report_progress`. |

### xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-16 | VP2.2 | `_VP22` on 16 tests in `test_terminal_verdict_policy.py` + both tests in `test_post_run_terminal_gate.py` | Suite is now 22/22 real passes. Direct pins added: `validation_state_from_tool_context`, `_is_review_mode`, `has_failed_required_static_check`. VP2 Final not flipped. |
| 2026-08-16 | VP2.3 (RED) | `test_approve_after_failed_run_static_checks_tool_is_rejected` added, xfail pending persist | Security-review medium: `run_static_checks_tool` does not persist rows on `ToolState`; `validation_state_from_tool_context` hardcodes `static_checks=[]`. Injected-row unit test kept. No `unavailable`/empty sibling — that pin would pass today without the persist field. |
| 2026-08-16 | VP2.3 | `test_approve_after_failed_run_static_checks_tool_is_rejected` xfail removed | Live-path is now a real pass (not XPASS). Direct pin added: `_persist_static_checks`. Injected-row unit test kept. VP2 Final / security-review not flipped. |
| 2026-08-16 | VP2.4 (RED) | `test_failed_static_check_survives_empty_plan_rerun` added, xfail pending sticky persist | Security-review medium: empty `plan_checks` (suffix-filtered no-op) assigns `ToolState.static_checks = []` and wipes a prior `failed` row. VP2.3 live-path stays a real pass. |

## Named symbols this suite pins

| Symbol | Module | Direct test |
|--------|--------|-------------|
| `validate_submission` | `mcp/verdict.py` | schema tests, D9, D4, approve+blocker, approve+failed gate, valid approve |
| `SubmissionValidation` | `mcp/verdict.py` | every validator test (`accepted` + closed `rejection_reason`; result is not a bool — D5) |
| `validation_state_from_tool_context` | `mcp/verdict.py` | `test_valid_approve_and_clear_gates_succeeds` (wires `tool_state` / `analyzer_run` / `terminal_submission` from `ToolContext`); `test_approve_after_failed_run_static_checks_tool_is_rejected` (must copy a `status: failed` row from `ToolState` — guard-deletion pin); `test_failed_static_check_survives_empty_plan_rerun` (failed row still present after empty-plan rerun) |
| `run_static_checks_tool` | `mcp/static_checks.py` | `test_approve_after_failed_run_static_checks_tool_is_rejected` (live failing command; payload `status == "failed"`); `test_failed_static_check_survives_empty_plan_rerun` (suffix-filtered empty plan must not wipe a prior `failed`) |
| `_persist_static_checks` | `mcp/static_checks.py` | `test_approve_after_failed_run_static_checks_tool_is_rejected` (callable + `ToolState.static_checks` carries a `status: failed` row after the live tool run — deleting the helper fails the suite) |
| `_classify_outcome` | `main_outcome.py` | `test_no_terminal_submission_is_inconclusive` (real `AgentResult`, not a mock), V3, D8, harness parity |
| `_is_review_mode` | `main_outcome.py` | `test_no_terminal_submission_is_inconclusive` (Review / IncrementalReview true; Build / `None` false; `Mode` object true) |
| `has_failed_required_static_check` | `agents/gates.py` | `test_approve_with_failing_required_deterministic_check_fails` (`failed` true; `passed` / empty false) |
| `get_unsubmitted_review` | `agents/post_run.py` | `test_unsubmitted_review_without_progress_comment_still_gates` |
| `run_post_run_retry_loop` | `agents/post_run.py` | `test_retry_exhaustion_yields_inconclusive_not_passed` |
| `decide_approval` | `agents/gates.py` | dropped / confirmed / publication pins; signature `findings, *, run_succeeded, tier` |
| `RunOutcome.inconclusive` | `run_outcome.py` | D2 core case; taxonomy stays six values |
| `AgentResult.terminal_submission_received` | `agents/shared.py` | D2, D8, D13, D4 finalize paths |
| `submit_review_verdict_tool` | `mcp/verdict.py` | D4 conflict / idempotent (policy layer on top of VP1); `test_approve_after_failed_run_static_checks_tool_is_rejected`; `test_failed_static_check_survives_empty_plan_rerun` |
| `create_pull_request_review_tool` | `mcp/review.py` | publication pin + existing-behaviour pin |
| `create_issue_comment_tool` / `report_progress_tool` | `mcp/comment.py` | `test_existing_review_and_comment_behaviour_unchanged` |

`validate_submission` / `SubmissionValidation` stay imported **inside test bodies** (collection-safe leftover from the RED wave).

### Closed `rejection_reason` vocabulary (D5)

| Reason | Class | Test |
|--------|-------|------|
| `invalid_verdict` | schema | `test_invalid_verdict_enum_rejected` |
| `unknown_fields` | schema | `test_unknown_fields_rejected` |
| `missing_required_fields` | schema | `test_missing_required_fields_rejected` |
| `request_changes_without_findings` | semantic | `test_request_changes_with_no_findings_is_semantically_rejected` (D9) |
| `approve_with_confirmed_blocker` | policy | `test_agent_approve_with_verified_blocker_fails_structurally` |
| `approve_with_failed_required_gate` | policy | `test_approve_with_failing_required_deterministic_check_fails` (injected rows); `test_approve_after_failed_run_static_checks_tool_is_rejected` (live tool path); `test_failed_static_check_survives_empty_plan_rerun` (failed row sticky across empty-plan rerun) |
| `conflicting_submission` | policy | `test_duplicate_conflicting_submissions_fail_closed` (D4) |

`state` duck-types `ToolState` plus `confirmed_findings`, `static_checks` (`run_static_checks` row shape: `name` + `status`), and `withdrawn_fingerprints`.

`_classify_outcome` grows a `mode` parameter. Before the final `return RunOutcome.passed`, review modes with `not result.terminal_submission_received` return `RunOutcome.inconclusive` with reason `"no terminal review verdict was submitted for this attempt"`. Do not add a seventh `RunOutcome` member.

## Contract matrix

| Decision | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| Valid approve + clear gates | Functional | Happy: validator accepts; classify with `received=True` is `passed`; trivial finding may approve | `test_valid_approve_and_clear_gates_succeeds` |
| Approve + confirmed blocker | Integration | Error: typed policy rejection **and** `decide_approval` is `"failure"` | `test_agent_approve_with_verified_blocker_fails_structurally` |
| Request-changes + blocker | Integration | Happy+gate: validator accepts; `decide_approval` still `"failure"` | `test_request_changes_with_verified_blocker_blocks` |
| **D2** missing verdict | Unit | Core: real `AgentResult(success=True, terminal_submission_received=False)` → `inconclusive`, not `failed`; Build still `passed` | `test_no_terminal_submission_is_inconclusive` |
| Prose is not a verdict | Unit | Edge: output `"LGTM"` is not a `decide_approval` input and cannot yield `passed` | `test_prose_lgtm_without_terminal_call_cannot_approve` |
| Schema enum / extra / required | Unit | Error: typed `SubmissionValidation`, not a bool | three schema tests |
| **D9** | Unit | Semantic: `request_changes` + `[]` rejected; reason is not `missing_required_fields` | `test_request_changes_with_no_findings_is_semantically_rejected` |
| **D4** conflict | Functional | Error: tool conflict + validator reject + finalize `received=False` → `inconclusive` | `test_duplicate_conflicting_submissions_fail_closed` |
| **D4** identical | Functional | Happy: same id, `received=True`, classify `passed` | `test_identical_resubmission_is_idempotent` |
| **V3** | Unit | Error: provider success without a verdict is not `passed` | `test_provider_success_without_verdict_is_not_a_successful_review` |
| **D8** fallback-eligible | Unit | Edge: missing **and** semantically rejected submissions keep `received=False` and map to `inconclusive` | `test_missing_verdict_leaves_run_fallback_eligible` |
| Fresh verdict | Unit | Happy: `received=True` → `passed`, not fallback-eligible (D13) | `test_fresh_valid_verdict_does_not_trigger_fallback` |
| Failed required gate | Unit | Error: `static_checks` row `status=failed` rejects `approve` | `test_approve_with_failing_required_deterministic_check_fails` |
| Failed required gate (live MCP) | Functional | Error: `run_static_checks_tool` failing command → `submit_review_verdict(approve)` rejected; `terminal_submission` unset (D8); `validation_state_from_tool_context` carries the `failed` row | `test_approve_after_failed_run_static_checks_tool_is_rejected` |
| Failed required gate (empty-plan rerun) | Functional | Error: suffix-filtered no-op `run_static_checks` must not wipe a prior `failed` row; `approve` still rejected; `terminal_submission` unset (D8) | `test_failed_static_check_survives_empty_plan_rerun` |
| Dropped finding | Unit | Regression: remainder does not fail; including the dropped Critical would | `test_verifier_dropped_finding_does_not_block_approval` |
| Confirmed finding | Unit | Regression: real `decide_approval`, not a reimplemented severity check | `test_verifier_confirmed_finding_blocks_approval` |
| Publication vs policy | Integration | Regression: GitHub `APPROVE` / `would_approve=True` cannot outvote a blocker | `test_publication_cannot_bypass_structural_policy` |
| Existing MCP review+comment | Functional | Regression: fingerprint, same-SHA skip, issue comment, progress | `test_existing_review_and_comment_behaviour_unchanged` |
| Harness parity | Unit | Happy: OpenCode-shaped and Codex-shaped `AgentResult` → same `inconclusive` | `test_both_harness_paths_obey_the_same_contract` |
| **V4** progress-comment precondition | Unit | Edge: `had_progress_comment=False` still gates; `tool_state.review` does not satisfy; `terminal_submission` does | `test_unsubmitted_review_without_progress_comment_still_gates` |
| **V4** retry exhaustion | Integration | Error: `MAX_POST_RUN_RETRIES` resumes, then `inconclusive` not `passed`/`failed` | `test_retry_exhaustion_yields_inconclusive_not_passed` |

No source-grep assertions. `_classify_outcome` is called with a real `AgentResult`. Confirmed/dropped approval tests call real `decide_approval`.

## RED acceptance (VP2.1)

22 collected; 4 pass (the `decide_approval` / existing review+comment pins); 18 xfail pending VP2.2. Zero collection errors. `make lint` and `make typecheck` clean. Product code is not edited in this wave.

## VP2.2 xfail reconciliation

22 collected; 22 pass; 0 xfail / 0 XPASS on `tests/review/test_terminal_verdict_policy.py` + `tests/review/test_post_run_terminal_gate.py`. Markers cleared; three previously zero-test-ref symbols pinned by extra assertions in existing tests. Product code is not edited in this wave. VP2 Final remains open.

## VP2.3 RED (security-review follow-up)

`test_approve_after_failed_run_static_checks_tool_is_rejected` drives the live MCP path: a configured failing `StaticCheckConfig` through `run_static_checks_tool`, then `submit_review_verdict_tool(approve)`. It must reject with `approve_with_failed_required_gate`, leave `terminal_submission` unset (D8), and show a `status: failed` row on `validation_state_from_tool_context(ctx).static_checks`. The injected-row unit test stays. No `unavailable`/empty-checks sibling — `has_failed_required_static_check` already treats only `failed` as negative, and that pin would pass today without persisting rows.

Expect: existing 22 VP2 policy tests pass; the new test xfails (`strict=False`) until ToolState persist + copy in `validation_state_from_tool_context`. Product code is not edited in this wave. VP2 Final remains open (security-review still `[ ]`).

## VP2.3 xfail reconciliation

23 VP2 policy tests across `tests/review/test_terminal_verdict_policy.py` (21) + `tests/review/test_post_run_terminal_gate.py` (2); 21/21 pass on the policy file; 0 xfail / 0 XPASS. Live-path `test_approve_after_failed_run_static_checks_tool_is_rejected` is a real pass. `_persist_static_checks` now has a direct `tests/` reference. Product code is not edited in this wave. VP2 Final remains open (security-review still `[ ]`).

## VP2.4 RED (security-review follow-up — empty-plan wipe)

`test_failed_static_check_survives_empty_plan_rerun` drives two live `run_static_checks_tool` calls: a failing `.py` gate, then a suffix-filtered `README.md` rerun that plans no checks. `approve` must still reject with `approve_with_failed_required_gate`, leave `terminal_submission` unset (D8), and keep a `status: failed` row on `validation_state_from_tool_context`. `StaticCheckConfig.suffixes` is pinned as a tuple. The VP2.3 live-path test stays a real pass.

Expect: existing policy tests pass; VP2.3 live-path passes; the new test xfails (`strict=False`) until empty `plan_checks` stops clearing `ToolState.static_checks` and any `failed` this session stays sticky. Product code is not edited in this wave. VP2 Final remains open (security-review still `[ ]`).
