# Review integrity HA2 — semantic fallback on missing terminal verdict — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md` PR HA2
Worktree: `mergecraft-ha2-semantic-fallback` @ `wave/ha2-semantic-fallback`

## xfail schedule

| Wave | Test files | Marker |
|------|------------|--------|
| **HA2.2** | `tests/agents/test_semantic_fallback.py` — five unimplemented contracts below | *(markers removed 2026-08-16 after HA2.2)* |

Pins that stayed **plain** (no xfail) through HA2.1, including the two D13 "usable verdict" cases that already held under today's `if result.success: stop` short-circuit:

- `test_runtime_failure_still_triggers_fallback`
- `test_valid_request_changes_does_not_trigger_fallback`
- `test_valid_approve_does_not_trigger_fallback`
- `test_fallback_index_still_stamped`
- `test_allow_fallback_false_still_blocks`

### xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-16 | HA2.2 | five `green after HA2.2: semantic fallback` markers (`_XFAIL_HA2`) | Suite is now 10/10 real passes. Direct pins added: `_classify_skip_reason` and `_retryable_failure_reason` (deleting either helper fails `test_fallback_reason_is_recorded_and_distinct`). |

## Named symbols this suite pins

| Symbol | Module | Direct test |
|--------|--------|-------------|
| `run_with_model_chain` | `utils/agent_resolve.py` | every test in `test_semantic_fallback.py` (real chain, scripted `run_once`) |
| `AgentResult.terminal_submission_received` | `agents/shared.py` | `test_provider_success_without_verdict_triggers_fallback`, D13 pins, both-harness pin |
| `FallbackReason` | `utils/agent_resolve.py` | `test_fallback_reason_is_recorded_and_distinct` |
| `fallback_reason` metadata stamp | `utils/agent_resolve.py` (`_attach_model_evidence`) | `test_fallback_reason_is_recorded_and_distinct`, `test_malformed_submission_triggers_fallback`, `test_stale_primary_result_is_not_reused_by_fallback` |
| `_attach_model_evidence` `fallback_index` / `fallback_occurred` | `utils/agent_resolve.py` | `test_fallback_index_still_stamped` |
| `_classify_skip_reason` | `utils/agent_resolve.py` | `test_fallback_reason_is_recorded_and_distinct` (usable → `None`; missing verdict / malformed / stale / retryable failure) |
| `_retryable_failure_reason` | `utils/agent_resolve.py` | `test_fallback_reason_is_recorded_and_distinct` (`timeout` / `crash` / `provider_error` from error text and metadata) |
| `ModelFallbackPolicyError` | `utils/agent_resolve.py` | `test_allow_fallback_false_still_blocks` |
| D13 usable `request_changes` | chain loop | `test_valid_request_changes_does_not_trigger_fallback` |

`FallbackReason` is imported at module level now that HA2.2 landed the enum.

## Locked D13

Fallback triggers on `not result.terminal_submission_received`, **not** on verdict content. A valid `request_changes` (findings present) is a usable result. "Review failed" (`no_terminal_verdict`, `malformed_submission`, `provider_error`, `timeout`, `crash`, `semantic_rejection`, `stale_attempt`) is not "review says PR fails". `semantic_rejection` is a validator-rejected submission (D8), never a valid `request_changes`.

Closed enum values: `provider_error`, `timeout`, `crash`, `no_terminal_verdict`, `malformed_submission`, `semantic_rejection`, `stale_attempt`.

## Contract matrix

| Decision | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| Retryable runtime failure still advances | Functional | Happy/regression: `success=False` + `retryable=True` walks to the next slug | `test_runtime_failure_still_triggers_fallback` |
| **D13 / H2** provider success ≠ review | Functional | Error-as-incompletion: `success=True` and `terminal_submission_received=False` advances | `test_provider_success_without_verdict_triggers_fallback` |
| Malformed submission is incompletion | Functional | Error: schema-invalid diagnostic + no recorded terminal; chain advances; reason is `malformed_submission` | `test_malformed_submission_triggers_fallback` |
| **D13** valid `request_changes` is usable | Functional | Happy + guard-deletion: recorded terminal, verdict content is `request_changes` with findings; chain does **not** advance; reason is not `no_terminal_verdict` | `test_valid_request_changes_does_not_trigger_fallback` |
| Valid `approve` is usable | Functional | Happy: recorded terminal `approve`; chain does not advance | `test_valid_approve_does_not_trigger_fallback` |
| Reason enum is closed and distinct | Unit + functional | Error/happy: enum membership; missing-verdict stamps `no_terminal_verdict`; usable `request_changes` does not; retryable provider error stamps `provider_error` | `test_fallback_reason_is_recorded_and_distinct` |
| Skip-reason helpers | Unit | Direct: `_classify_skip_reason` / `_retryable_failure_reason` map usable, missing-verdict, malformed, stale, timeout, crash, provider_error | `test_fallback_reason_is_recorded_and_distinct` |
| Fallback metadata stamp | Unit/functional | Regression: after a runtime fallback, `fallback_index==1` and `fallback_occurred is True` | `test_fallback_index_still_stamped` |
| `allow_fallback=false` | Functional | Error: retryable primary failure raises `ModelFallbackPolicyError`; secondary is never called | `test_allow_fallback_false_still_blocks` |
| Stale attempt is not reused | Functional | Edge: fallback `run_once` returns an `AgentResult` whose `diagnostics.attempt_id` does not match the current attempt; chain skips it; reason is `stale_attempt`; returned object is not the stale one | `test_stale_primary_result_is_not_reused_by_fallback` |
| Harness-agnostic chain decision | Integration | Happy: OpenCode-shaped and Codex-shaped `AgentResult` (`success=True`, `terminal_submission_received=False`, harness `AgentUsage`) both advance | `test_both_harnesses_obey_the_rule` |

Every test builds outcomes as real `AgentResult` values and passes them through `run_with_model_chain`. There is no reimplemented walk loop and no source grep.

## RED acceptance (HA2.1)

10 collected; **5 passed / 5 xfailed**. The three named pins pass today, and so do the two D13 usable-verdict tests (`test_valid_request_changes_does_not_trigger_fallback`, `test_valid_approve_does_not_trigger_fallback`) against the current `if result.success` short-circuit — they are not xfail, so they become the guard-deletion proof after HA2.2. Five tests xfail pending HA2.2. Zero collection errors. `make lint` and `make typecheck` clean. Product code is not edited in this wave.

## Reconciliation (post-HA2.2)

10 collected; 10 passed; 0 xfail; 0 xpass. `_classify_skip_reason` and `_retryable_failure_reason` now have direct `tests/` references. HA2 Final checkboxes are not flipped here.

## Escalation (coverage-gate)

`make_agent_result(success=True)` in `tests/tracing/instrumentation/conftest.py` now defaults `terminal_submission_received=True` so canned success is a usable D13 winner; pass `terminal_submission_received=False` to script incomplete success. `AgentResult` in `src/` is unchanged.
