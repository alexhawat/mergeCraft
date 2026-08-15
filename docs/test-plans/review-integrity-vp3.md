# Review integrity VP3 — terminal-verdict shadow protocol — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md`
Worktree: `mergecraft-vp3-shadow` @ `wave/vp3-shadow` (stacked on VP2 `087df16`)

## xfail schedule

| Wave | Test files | Marker |
|------|------------|--------|
| **VP3.2** | `tests/evidence/test_verdict_shadow.py` (all 5) | *(markers removed 2026-08-16 after VP3.2)* |
| **VP3.2** | `tests/tracing/test_verdict_diagnostics.py` (both) | *(markers removed 2026-08-16 after VP3.2)* |
| **VP3.2** | `tests/review/test_attempt_attribution.py` (both) | *(markers removed 2026-08-16 after VP3.2)* |

Never `strict=True` — `xfail_strict = true` in `pyproject.toml` would turn a later XPASS into a hard failure the impl wave cannot touch.

Existing gate-action shadow tests in `tests/evidence/test_gate_actions.py` are not part of this suite and must keep collecting. Their leftover W9/W10 xfails are unchanged.

### xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-16 | VP3.2 | `_VP32` on all 5 tests in `test_verdict_shadow.py`, both tests in `test_verdict_diagnostics.py`, and both tests in `test_attempt_attribution.py` | Suite is now 9/9 real passes (0 xfail / 0 XPASS). Direct pin added: `VerdictProtocolPrediction`. Gate-action W9/W10 xfails in `test_gate_actions.py` left in place. VP3 Final not flipped. |

## Named symbols this suite pins

| Symbol | Module | Direct test |
|--------|--------|-------------|
| `predict_verdict_protocol` | `evidence/shadow.py` | all five tests in `test_verdict_shadow.py` |
| `VerdictProtocolPrediction` | `evidence/shadow.py` | `test_shadow_records_prediction_without_changing_outcome` (`isinstance` pin) |
| `record_shadow_prediction` | `evidence/shadow.py` | `test_shadow_records_prediction_without_changing_outcome`, agreement, diagnostic-on-row |
| `disagree_with_outcome` | `evidence/shadow.py` | `test_disagreement_is_queryable` (also agreement fallback) |
| `VerdictDiagnostic` | `mcp/verdict.py` | `test_shadow_row_carries_diagnostic_code`, `test_each_diagnostic_reaches_the_span` |
| `span_attrs_for_verdict_diagnostic` | `mcp/verdict.py` | both tests in `test_verdict_diagnostics.py` |
| `redact_attrs` / `redact_event` | `tracing/redaction.py` | `test_each_diagnostic_reaches_the_span`, `test_diagnostics_are_redacted` (guard-deletion) |
| `GatesSettings.terminal_verdict` | `config/settings.py` | shadow default in `test_shadow_records_prediction_without_changing_outcome`; enforce in `test_enforce_mode_changes_the_outcome` |
| `_classify_outcome(..., verdict_protocol=)` | `main_outcome.py` | shadow vs enforce outcome tests |
| `stamp_attempt_id` | `utils/agent_resolve.py` | both tests in `test_attempt_attribution.py` |
| `ToolState.attempt_id` | `mcp/tool_state.py` | `test_verdict_is_bound_to_its_attempt` (stamped beside `fallback_index`) |
| `TerminalSubmission.attempt_id` | `mcp/tool_state.py` | `test_verdict_is_bound_to_its_attempt` |
| `verdict_satisfies_attempt` | `mcp/verdict.py` | `test_stale_structural_result_is_not_reused` |
| `finalize_agent_result` | `agents/post_run.py` | stale-attempt guard-deletion pin |

`predict_verdict_protocol`, `VerdictProtocolPrediction`, `VerdictDiagnostic`, `span_attrs_for_verdict_diagnostic`, `stamp_attempt_id`, and `verdict_satisfies_attempt` are imported **inside test bodies**.

### Closed `VerdictDiagnostic` vocabulary

Snake_case `StrEnum` members (name == value), eight values, no more:

| Member | Plan wording | Typical producer |
|--------|--------------|------------------|
| `provider_failure` | provider failure | `result.success is False` |
| `provider_success_without_submission` | provider success w/o submission | VP2 missing-verdict branch |
| `schema_invalid` | schema-invalid | validator schema rejection |
| `semantic_invalid` | semantic-invalid | D9 / malformed submission |
| `policy_rejection` | policy rejection | approve + failed required gate / conflict |
| `agent_approved_but_blocked` | agent-approved-but-blocked | approve + confirmed blocker |
| `approved` | approved | valid `approve` + clear gates |
| `fallback_triggered` | fallback-triggered | HA2 semantic fallback |

## Contract matrix

| Decision | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| **D6** shadow does not flip the gate | Functional | Happy/edge: missing verdict + `verdict_protocol="shadow"` still reports legacy `passed`; a JSONL row is written with predicted `inconclusive` / `provider_success_without_submission` | `test_shadow_records_prediction_without_changing_outcome` |
| Agreement when a verdict is present | Functional | Happy: both sides `passed` / `approved`; row `disagreement` is false | `test_shadow_records_agreement_when_verdict_present` |
| Diagnostic on the shadow row | Unit | Happy: closed `VerdictDiagnostic` value is on the row (`diagnostic` / `verdict_diagnostic`) | `test_shadow_row_carries_diagnostic_code` |
| Enforce fires the VP2 branch | Unit | Error: `verdict_protocol="enforce"` + missing verdict → `RunOutcome.inconclusive` and the VP2 reason string | `test_enforce_mode_changes_the_outcome` |
| **D6** disagreement is queryable | Unit | Edge: predicted `inconclusive` vs actual `passed` is a disagreement; matching `passed` is not. Guard-deletion: collapsing both onto a generic "review" direction hides the mismatch | `test_disagreement_is_queryable` |
| Eight diagnostics reach the span | Integration | Happy: each closed value appears on span attrs produced by `span_attrs_for_verdict_diagnostic`, and survives `redact_attrs` | `test_each_diagnostic_reaches_the_span` |
| Redaction before surfacing | Integration | Guard-deletion: a `sk-…` submission summary must not appear on the helper's returned attrs. The test does **not** re-apply `redact_attrs` to that output | `test_diagnostics_are_redacted` |
| **V7** verdict bound to attempt | Functional | Happy: `stamp_attempt_id(..., attempt_id=2)` then `submit_review_verdict` records `TerminalSubmission.attempt_id == 2`; finalize copies it into `diagnostics` | `test_verdict_is_bound_to_its_attempt` |
| **V7** stale result is not reused | Integration | Error: leftover `attempt_id=0` submission does not satisfy current attempt 1; `finalize_agent_result` leaves `terminal_submission_received=False`. Pairs with HA2 `stale_attempt` | `test_stale_structural_result_is_not_reused` |

No source-grep assertions. Shadow tests drive the real `record_shadow_prediction` / `disagree_with_outcome` once the predicate exists. `_classify_outcome` is called with a real `AgentResult`. Stale-attempt goes through real `finalize_agent_result`.

## Impl notes for VP3.2

- Reuse `evidence/shadow.py`. Extend `record_shadow_prediction` with a `prediction=` (and `actual_outcome=`) kwarg so a verdict-protocol row lands in the **same** JSONL as gate-action rows. Do not add a second log file.
- `predict_verdict_protocol(result, *, mode)` is the predicate alongside `predict_action`. Return shape must expose `.outcome` / `.predicted_outcome` and `.diagnostic`.
- `_classify_outcome` grows `verdict_protocol: Literal["shadow", "enforce"]`. Shadow skips the VP2 missing-verdict branch (legacy `passed`); enforce fires it. `GatesSettings.terminal_verdict` defaults to `"shadow"` (D6 / D12 pattern).
- `disagree_with_outcome` must treat protocol outcomes (`passed` vs `inconclusive`) as distinct directions — today's merge/block/review mapping folds both onto `"review"` and would hide the mismatch.
- `stamp_attempt_id(tool_state, *, attempt_id, fallback_index)` sets `tool_state.attempt_id` beside `fallback_index` when the model chain starts an attempt. `submit_review_verdict` copies that stamp onto `TerminalSubmission`.
- `verdict_satisfies_attempt(submission, *, current_attempt_id)` is the freshness predicate; `_terminal_submission_fields` / `finalize_agent_result` must consult it.
- `span_attrs_for_verdict_diagnostic(diagnostic, *, summary)` returns span attrs (key `verdict.diagnostic` or equivalent) after `redact_attrs`. Putting the diagnostic on the span without going through `tracing/redaction.py` fails the redaction test.

## RED acceptance (VP3.1)

9 collected; 0 pass; 9 xfail pending VP3.2. Zero collection errors. `make lint` and `make typecheck` clean. Product code is not edited in this wave. VP3.2 / VP3 Final checkboxes are not flipped here.

## VP3.2 xfail reconciliation

9 collected; 9 pass; 0 xfail / 0 XPASS on `tests/evidence/test_verdict_shadow.py` + `tests/tracing/test_verdict_diagnostics.py` + `tests/review/test_attempt_attribution.py`. Markers cleared; `VerdictProtocolPrediction` directly pinned. Gate-action leftover xfails in `tests/evidence/test_gate_actions.py` unchanged. Product code is not edited in this wave. VP3 Final remains open.
