# Review integrity VP4 — enforce flip and publication split — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md`
Worktree: `mergecraft-vp4-enforce-publish` @ `wave/vp4-enforce-publish` (stacked on VP3 `b65cdb5`)

## xfail schedule

| Wave | Test files | Marker |
|------|------------|--------|
| **VP4.2** | `tests/review/test_publication_split.py` — delegate, publication-requires-submission, publisher-not-a-tool | *(markers removed 2026-08-16 after VP4.2)* |
| **VP4.2** | `tests/review/test_enforcement_flip.py::test_enforce_is_default_after_this_pr` | *(markers removed 2026-08-16 after VP4.2)* |
| **VP4.2** | `tests/prompts/test_terminal_protocol_prompt.py` — Review + IncrementalReview contract tests | *(markers removed 2026-08-16 after VP4.2)* |
| **VP4.2** | `tests/review/test_phase_guards.py` (both) | *(markers removed 2026-08-16 after VP4.2)* |
| **VP4.3** | `tests/review/test_publication_split.py::test_body_only_unapproved_legacy_review_does_not_github_approve` | *(markers removed 2026-08-16 after VP4.3)* |
| **VP4.3** | `tests/review/test_phase_guards.py::test_create_pull_request_review_before_scope_is_rejected` | *(markers removed 2026-08-16 after VP4.3)* |
| **VP4.4** | `tests/review/test_publication_split.py::test_stale_approve_replay_does_not_github_approve_after_blocker` | `@pytest.mark.xfail(reason="green after VP4.4: re-validate before publish on hash match", strict=False)` |

Never `strict=True` — `xfail_strict = true` in `pyproject.toml` would turn a later XPASS into a hard failure the impl wave cannot touch.

### Compatibility pins (pass on the VP4.1 tree)

| Test | Why it is green today |
|------|------------------------|
| `test_legacy_tool_still_registered` | D7: `create_pull_request_review` stays in `build_common_tools` and `build_orchestrator_tools` |
| `test_shadow_can_still_be_selected` | D6 escape hatch: `RepoSettings` still accepts `gates.terminal_verdict: shadow` |
| `test_no_other_prompt_content_changed` | Snapshot of this branch's `Review` / `IncrementalReview` `TEMPLATE` strings at VP4.1, equality outside the terminal-protocol paragraph |

### xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-16 | VP4.2 | `_VP42_DELEGATE`, `_VP42_PUBLISH`, `_VP42_INTERNAL` on `test_publication_split.py`; `_VP42` on `test_enforcement_flip.py`; `_VP42_REVIEW`, `_VP42_INCREMENTAL` on `test_terminal_protocol_prompt.py`; `_VP42_SCOPE`, `_VP42_TRACE` on `test_phase_guards.py` | Suite is now 11/11 real passes (0 xfail / 0 XPASS). Direct pins added: `record_validated_terminal_submission`, `stamp_review_phase_on_active_span`. `pending_review_publication` pinned as a `ToolState` field. VP4 Final not flipped. |
| 2026-08-16 | coverage-gate (Job A) | n/a (real passes, not xfails) | `test_shadow_records_prediction_without_changing_outcome` now pins `default_settings().gates.terminal_verdict == "enforce"` (D6); shadow-escape-hatch behaviour still driven via `_classify(..., verdict_protocol="shadow")`. `test_mode_prompt_text_is_byte_identical_after_split` compares Review / IncrementalReview **outside** the File 3/4 terminal-protocol paragraph (same markers as `test_terminal_protocol_prompt.py`); every other mode and both descriptions stay byte-identical. Snapshot fixture not rewritten. |
| 2026-08-16 | VP4.3 | body-only `approved=false` xfail on `test_publication_split.py`; before-scope xfail on `test_phase_guards.py` | Suite scoped modules are real passes (0 xfail / 0 XPASS). Direct pin added: `ensure_review_scope_for_terminal`. IncrementalReview INIT + `incremental_changed_paths` exemption not pinned (would expand the suite). VP4 Final `security-review` and `make ci-resume` not flipped. |

## Named symbols this suite pins

| Symbol | Module | Direct test |
|--------|--------|-------------|
| `create_pull_request_review_tool` | `mcp/review.py` | `test_create_pull_request_review_delegates_to_recorder`, `test_legacy_tool_still_registered`, `test_body_only_unapproved_legacy_review_does_not_github_approve`, `test_create_pull_request_review_before_scope_is_rejected`, `test_stale_approve_replay_does_not_github_approve_after_blocker` |
| `_legacy_params_to_submission` | `mcp/review.py` | `test_body_only_unapproved_legacy_review_does_not_github_approve` (mapped `verdict` is not `"approve"`; guard-deletion: fallthrough `return {"verdict": "approve", ...}` must fail) |
| `validate_submission` | `mcp/verdict.py` | `test_create_pull_request_review_delegates_to_recorder` (mapped approve + confirmed blocker is rejected; live tool must not bypass); `test_stale_approve_replay_does_not_github_approve_after_blocker` (same mapped payload must fail after the blocker is attached) |
| `record_validated_terminal_submission` | `mcp/verdict.py` | `test_create_pull_request_review_delegates_to_recorder` (`callable` pin on the public recorder the delegate uses); `test_stale_approve_replay_does_not_github_approve_after_blocker` (hash-match replay must not skip re-validation before GitHub publish) |
| `stamp_review_phase_on_active_span` | `mcp/verdict.py` | `test_phase_reaches_the_trace` (`callable` pin; live `checkout_pr` stamps `review.phase`) |
| `publish_pull_request_review` | `mcp/review.py` | `test_publication_requires_a_validated_submission`, `test_publisher_is_not_an_mcp_tool` |
| `ToolSpec` | `mcp/shared.py` | `test_publisher_is_not_an_mcp_tool` (publisher is callable and is not a `ToolSpec`) |
| `build_common_tools` / `build_orchestrator_tools` | `mcp/server.py` | `test_legacy_tool_still_registered`, `test_publisher_is_not_an_mcp_tool` |
| `GatesSettings.terminal_verdict` / `default_settings` | `config/settings.py` | `test_enforce_is_default_after_this_pr`, `test_shadow_can_still_be_selected` |
| `RepoSettings` | `config/settings.py` | `test_shadow_can_still_be_selected` |
| `Review.TEMPLATE` / `IncrementalReview.TEMPLATE` | `modes/Review.py`, `modes/IncrementalReview.py` | both contract tests + `test_no_other_prompt_content_changed` |
| `compute_modes` / `format_mcp_tool_ref` | `modes/__init__.py`, `types.py` | both prompt contract tests (`${t("submit_review_verdict")}` interpolates) |
| `ReviewPhase` | `mcp/verdict.py` | `test_phase_reaches_the_trace` (closed member sequence) |
| `ToolState.review_phase` | `mcp/tool_state.py` | `test_phase_reaches_the_trace` (advanced by live `checkout_pr`) |
| `submit_review_verdict_tool` | `mcp/verdict.py` | `test_submit_before_scope_is_rejected`, `test_stale_approve_replay_does_not_github_approve_after_blocker` (first-call success with empty analyzer state) |
| `ensure_review_scope_for_terminal` | `mcp/verdict.py` | `test_create_pull_request_review_before_scope_is_rejected` (`callable` pin on the D10 guard the legacy tool shares with `submit_review_verdict`) |
| `checkout_pr_tool` | `mcp/checkout.py` | `test_phase_reaches_the_trace` |
| `ApprovalRecord` / `ToolState.approval` | `mcp/tool_state.py` | `test_create_pull_request_review_delegates_to_recorder` (must stay unset on rejection); `test_stale_approve_replay_does_not_github_approve_after_blocker` (second call must not record a successful GitHub approve) |
| `ToolState.terminal_submission` | `mcp/tool_state.py` | delegate + publication + submit-before-scope (D8: unset on reject) |
| `ToolState.pending_review_publication` | `mcp/tool_state.py` | `test_publication_requires_a_validated_submission` (unset when no validated submission) |

`ReviewPhase`, `publish_pull_request_review`, `validate_submission`, `record_validated_terminal_submission`, `stamp_review_phase_on_active_span`, `ensure_review_scope_for_terminal`, and `_legacy_params_to_submission` are imported **inside test bodies**.

### Closed `ReviewPhase` vocabulary

StrEnum members, name == value, ten values, no more, in this order:

| Member | Advanced by (plan File 2) |
|--------|---------------------------|
| `INIT` | default on `ToolState` |
| `ESTABLISH_SCOPE` | `checkout_pr` |
| `COLLECT_EVIDENCE` | `run_analyzers` |
| `REVIEW` | (in-progress review) |
| `NORMALIZE` | (finding normalize) |
| `VERIFY_BLOCKERS` | `record_finding_verdict` |
| `SUBMIT` | `submit_review_verdict` |
| `POLICY` | policy evaluation after submit |
| `PUBLISH` | internal publisher |
| `COMPLETE` | terminal |

D10: a `ReviewPhase` StrEnum plus guard clauses in four existing tools — no new framework, no new package.

## Contract matrix

| Decision | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| **D7** legacy tool delegates | Functional | Error / guard-deletion: live `create_pull_request_review(approved=True)` with a confirmed blocker (payload `validate_submission` would reject) errors, leaves `terminal_submission` unset, does not write `ApprovalRecord`, does not post to GitHub | `test_create_pull_request_review_delegates_to_recorder` |
| **D7** tool remains registered | Integration | Happy / compatibility: name `create_pull_request_review` is in orchestrator and common (reviewer-visible) toolsets | `test_legacy_tool_still_registered` |
| **V6** publish needs a verdict | Functional | Error: `publish_pull_request_review` without a validated `terminal_submission` is an error and posts nothing | `test_publication_requires_a_validated_submission` |
| **V6** publisher is internal | Unit + integration | Happy: function exists, is not a `ToolSpec`, and is absent from every `build_*_tools` name set | `test_publisher_is_not_an_mcp_tool` |
| **D6** enforce is the new default | Unit | Happy (after VP4.2): `default_settings().gates.terminal_verdict == "enforce"` | `test_enforce_is_default_after_this_pr` |
| **D6** shadow escape hatch | Unit | Happy / compatibility: explicit `shadow` still validates | `test_shadow_can_still_be_selected` |
| File 3 Review prompt | Functional | Happy: `TEMPLATE` contains `${t("submit_review_verdict")}` exactly once; rendered `compute_modes("claude")` prompt names the interpolated ref exactly once | `test_review_prompt_states_the_contract` |
| File 4 IncrementalReview prompt | Functional | Same contract for IncrementalReview | `test_incremental_review_prompt_states_the_contract` |
| Out-of-scope prompt guard | Unit | Regression: equality of both templates vs `tests/prompts/fixtures/*_vp4_1.txt` **outside** the terminal-protocol paragraph | `test_no_other_prompt_content_changed` |
| **D10** submit-before-scope | Functional | Error: live `submit_review_verdict` before `checkout_pr` established scope is an error; D8 `terminal_submission` unset | `test_submit_before_scope_is_rejected` |
| **D10** phase on the trace | Integration | Happy: live `checkout_pr` advances `ToolState.review_phase` to `ESTABLISH_SCOPE` and `review.phase` (or equivalent) appears on a span attr | `test_phase_reaches_the_trace` |
| **VP4.3** body-only `approved: false` | Functional | Error / guard-deletion: `_legacy_params_to_submission` must not map body-only `approved=False` to `verdict="approve"`; live `create_pull_request_review` must not GitHub-APPROVE. Rejecting the attempt (D8 unset + empty payloads) is also a pass | `test_body_only_unapproved_legacy_review_does_not_github_approve` |
| **VP4.3 / D10** legacy tool before scope | Functional | Error: live `create_pull_request_review(approved=True)` while `review_phase` is still `INIT` errors (text names scope/phase/checkout); D8 `terminal_submission` unset; no `ApprovalRecord`; GitHub payloads empty | `test_create_pull_request_review_before_scope_is_rejected` |
| **VP4.4** stale approve replay after blocker | Functional | Error / guard-deletion: live `submit_review_verdict(approve)` with empty analyzer state, then attach a confirmed Critical blocker, then live `create_pull_request_review(approved=True, body=same summary)`. No GitHub payload may have `event=APPROVE` (empty payloads pass). Tool result is an error **or** publication is skipped/rejected. `ApprovalRecord` must not show a successful GitHub approve from the second call. Do not require wiping the earlier `terminal_submission` (D8 is for a rejected first attempt). D4 still applies to `submit_review_verdict` when state has **not** changed. If submit hashes raw params vs mapped `{verdict,summary,findings}` and the second call conflicts instead of replaying, assert no APPROVE anyway | `test_stale_approve_replay_does_not_github_approve_after_blocker` |

No source-grep assertions. Delegate and phase tests drive the real tools. Prompt tests drive `compute_modes` (the same `${t("...")}` expansion the modes already use). The byte-diff pin snapshots **this branch at VP4.1**, not `origin/pre-0.0.1`, because VP1–VP3 already sit on this stack; the excluded region is Review step 7's opening (through the coverage-nudge note, keeping the callout ladder) and IncrementalReview step 10's opening (keeping the callout ladder / IF–ELSE).

## Impl notes for VP4.2

- `create_pull_request_review_tool` constructs the same submission shape (`verdict` / `summary` / `findings`) and routes through `validate_submission` + the recorder used by `submit_review_verdict`. It must not write `ApprovalRecord` on a rejected attempt. GitHub posting moves to `publish_pull_request_review` in `mcp/review.py` (not a `ToolSpec`, not registered).
- `GatesSettings.terminal_verdict` default flips from `"shadow"` to `"enforce"`. `"shadow"` remains a valid `GateMode`.
- `ReviewPhase` lives in `mcp/verdict.py` and is stored on `ToolState.review_phase`. Guard `submit_review_verdict` until `checkout_pr` has advanced the phase to `ESTABLISH_SCOPE` (or later). Stamp `review.phase` on the active span (`current_tracer()` / `_ACTIVE_SPAN`) so a wrapping `tool.call` span carries it.
- Prompt File 3/4: replace only the terminal-protocol paragraph so `test_no_other_prompt_content_changed` stays green. Name the terminal act with `${t("submit_review_verdict")}` exactly once in each template.

## RED acceptance (VP4.1)

11 collected; 3 pass (legacy tool registered, shadow still selectable, prompt byte-diff pin); 8 xfail pending VP4.2. Zero collection errors. `make lint` and `make typecheck` clean. Product code is not edited in this wave. VP4.2 / VP4 Final checkboxes are not flipped here.

## VP4.2 xfail reconciliation

11 collected; 11 pass; 0 xfail / 0 XPASS on `tests/review/test_publication_split.py` + `tests/review/test_enforcement_flip.py` + `tests/prompts/test_terminal_protocol_prompt.py` + `tests/review/test_phase_guards.py`. Markers cleared; `record_validated_terminal_submission` and `stamp_review_phase_on_active_span` directly pinned; `pending_review_publication` pinned as a `ToolState` field. Product code is not edited in this wave. VP4 Final remains open.

## VP4.3 xfail reconciliation

Two medium findings. Markers cleared after VP4.3 impl (`e39f55b`). Product code is not edited in this wave. VP4 Final `security-review` and `make ci-resume` stay open.

- `_legacy_params_to_submission` is imported **inside the test body**.
- `create_pull_request_review_tool` before-scope is the D10 pin the new-tool path already has (`test_submit_before_scope_is_rejected`); the legacy tool must obey it too.
- `ensure_review_scope_for_terminal` is imported **inside the before-scope test body** (`callable` pin).

## VP4.4 RED (stale approve replay)

Residual medium from `security-review`. Idempotent replay in `record_validated_terminal_submission` returns the existing `approve` when `payload_hash` matches and skips `validate_submission`. Then `create_pull_request_review` can GitHub-`APPROVE` after a Critical blocker was confirmed later.

- `tests/review/test_publication_split.py::test_stale_approve_replay_does_not_github_approve_after_blocker` is xfail pending VP4.4 impl (`strict=False`). Existing tests in that file stay real passes.
- Setup: `selected_mode = "Review"`, `review_phase = ESTABLISH_SCOPE` (D10 must not fire), empty analyzer state, `pr_approve_enabled=True`, `trust_tier="trusted"`.
- Live sequence: `submit_review_verdict({verdict: "approve", summary: "Looks good.", findings: []})` must succeed (fixture error if not) → attach `_blocker()` as confirmed (`analyzer_run` + `verified_ids`) → live `create_pull_request_review({pull_number: 7, body: "Looks good.", approved: True})`.
- The security finding assumes hashes match when `summary == body`. If they would not (submit hashing raw params vs mapped `{verdict,summary,findings}`), the live sequence still runs; a D4 conflict instead of replay is still a pass for **no GitHub APPROVE**.
- D4 (identical retry is idempotent) is **not** weakened for `submit_review_verdict` when state has not changed. This pin is publication-time re-validation when blockers now exist.
- Product code is not edited in this wave. VP4 Final `security-review` is not flipped.
