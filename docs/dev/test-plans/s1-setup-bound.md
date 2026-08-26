# PR S1 — Setup-script bound + fail-closed policy — test plan (S1.1 RED)

Wave plan: `.ignorelocal/waves/issues-setup-container-hygiene-wave-plan.md`
Worktree: `mergecraft-rfc-s1-setup-bound` @ `wave/rfc-s1-setup-bound`

## Locked decisions (D-table rows that bind this suite)

| # | Topic | Bound test |
|---|-------|------------|
| **D5** | Setup failure → `RunOutcome.inconclusive`, **not** `configuration_error` | tests 1, 2 |
| **D6** | `setup_hook_failure` is **wired**, not deleted — `instructions.py:454-458` becomes reachable | tests 16, 17 |
| **D8** (out of scope for S1, no test) | — | — |
| **D10** | `setupFailurePolicy` (`inconclusive` \| `fail` \| `warn`, default `inconclusive`) | tests 8, 9, 10, 11 |

## Global conventions that bind this suite

- **Convention 6 — no widening `RunOutcome`.** Existing six-value taxonomy. S1 only adds *producers* of `inconclusive`; the suite never assumes a new outcome value.
- **Convention 7 — redact before surfacing.** Tests for stderr redaction assert the secret pattern is replaced by `<redacted>` (`REDACTION_SENTINEL`) in **both** the prompt and the `result` payload. Re-implementation in source is the impl wave's job — not the test's.
- **Convention 8 — trust check at `main.py:368` does NOT move.** Test 7 (`test_untrusted_tier_never_executes_setup_script`) pins that the gate still runs before any subprocess spawn.
- **Convention 9 — reuse `utils/process_group.py`.** Tests 12–14 hit the helper, not a private kill path.

## xfail / RED schedule

| Wave | Test files | Marker / status |
|------|------------|-----------------|
| **S1.1 (this wave)** | `tests/config/test_setup_script_failure.py`, `tests/config/test_setup_failure_policy.py`, `tests/config/test_setup_script_timeout.py`, `tests/prompts/test_setup_hook_failure_prompt.py` | 20 collected; **10 pass** today (5 explicit regression pins + 5 contract guards against existing helpers); **10 RED** pending S1.2 |

Per-creator convention the impl wave turns RED → green; the 10 pending tests are written as ordinary `def test_*` functions (no `xfail` markers) so a missing implementation shows as a natural failure the wave-verifier can read. **The 5 explicit regression pins must pass today.**

**Why more passes than the plan's nominal "5":** tests 2, 3, 12, 14, 16 cover contracts that already happen to be enforced by helpers / functions that exist today — `_structured_failure_result` (test 3), `utils.process_group.wait_or_kill_process_group` (tests 12 & 14), `RUN_OUTCOME_CONCLUSION[RunOutcome.inconclusive] == "neutral"` (test 2), and the `setup_hook_failure` parameter on `resolve_instructions` (test 16). These pass today; the impl wave does not need to touch them, but they guard against accidental regression during the S1.2 rewrite. The wave-verifier should still see them as green.

## Contract → test matrix

### 1. `tests/config/test_setup_script_failure.py` — 7 tests

| # | Test | Contract | Status |
|---|------|----------|--------|
| 1 | `test_trusted_setup_script_nonzero_exit_yields_inconclusive` | D5: trusted-tier non-zero exit → `RunOutcome.inconclusive` (not `passed`) | RED |
| 2 | `test_inconclusive_maps_to_neutral_check_conclusion` | `RUN_OUTCOME_CONCLUSION[RunOutcome.inconclusive] == "neutral"` (no widening) | RED |
| 3 | `test_setup_failure_reason_recorded_on_result_output` | structured `result` payload carries the redacted failure reason | RED |
| 4 | `test_setup_script_stderr_is_redacted_before_surfacing` | convention 7: `ghp_…` / `sk-…` in stderr becomes `<redacted>` (`REDACTION_SENTINEL`) in prompt **and** `result` | RED |
| 5 | `test_trusted_setup_script_zero_exit_still_passes` | **regression pin** — happy path today | PASS |
| 6 | `test_no_setup_script_configured_is_unaffected` | **regression pin** — empty `setup_script` is a clean pass | PASS |
| 7 | `test_untrusted_tier_never_executes_setup_script` | **regression pin** — convention 8: trust check precedes shell spawn | PASS |

### 2. `tests/config/test_setup_failure_policy.py` — 4 tests

| # | Test | Contract | Status |
|---|------|----------|--------|
| 8 | `test_policy_defaults_to_inconclusive` | D10: unset input → failure yields `inconclusive` | RED |
| 9 | `test_policy_fail_yields_configuration_error` | `setupFailurePolicy: fail` → `RunOutcome.configuration_error` | RED |
| 10 | `test_policy_warn_reproduces_legacy_continue` | `setupFailurePolicy: warn` → run continues **and** prompt carries failure text | RED |
| 11 | `test_invalid_policy_value_fails_closed` | unknown policy value → `configuration_error` | RED |

### 3. `tests/config/test_setup_script_timeout.py` — 4 tests

| # | Test | Contract | Status |
|---|------|----------|--------|
| 12 | `test_hanging_setup_script_is_killed_at_deadline` | F6: `sleep 600` with 2 s budget terminates promptly (real subprocess) | RED |
| 13 | `test_timed_out_setup_script_yields_inconclusive` | timeout → `inconclusive` with reason distinguishable from non-zero exit | RED |
| 14 | `test_setup_script_grandchildren_are_reaped` | backgrounds a child; after timeout **no** descendant survives. **Asserts on real process state**, mirroring `tests/security/test_process_tree_kill.py::test_timeout_kills_grandchildren`. | RED |
| 15 | `test_setup_timeout_is_deducted_from_the_run_budget` | a slow setup script does NOT silently extend the total run deadline | RED |

### 4. `tests/prompts/test_setup_hook_failure_prompt.py` — 5 tests (new directory `tests/prompts/`)

| # | Test | Contract | Status |
|---|------|----------|--------|
| 16 | `test_setup_hook_failure_branch_is_reachable` | F1: `resolve_instructions(setup_hook_failure="boom")` renders the `instructions.py:454-458` text | RED |
| 17 | `test_setup_hook_failure_empty_omits_branch` | **regression pin** — empty string omits the section | PASS |
| 18 | `test_skip_reason_reaches_prompt` | F3: `tool_state.setup_script_skip_reason` set → prompt states script was skipped and why | RED |
| 19 | `test_skip_reason_absent_omits_branch` | **regression pin** — absent skip reason omits the branch | PASS |
| 20 | `test_both_call_sites_pass_the_reason` | F1 structural pin: **the built prompt** from both primary and retry/fallback paths carries the reason. **Asserts on rendered output**, not on source-grep absence of `""`. | RED |

## Driving `main()` from tests

- Tests 1–4, 5–7, 8–11 use `tests/support/run_main_harness.py::run_main_for_test` (real `mergecraft.main.main()` driven with a fully scripted collaborator graph).
- Test 3 drives `_structured_failure_result` directly because the harness's success path bypasses `cli/gha_cmd.py`; the harness's `result.result` field carries the structured payload on the GHA path.
- Tests 12, 14 do NOT use the harness — they need real subprocess control (mirroring `test_timeout_kills_grandchildren`). Test 13 uses the harness with a fake that simulates a timed-out subprocess. Test 15 uses the harness with a slow fake to verify the agent deadline math.
- Tests 16–20 call `mergecraft.utils.instructions.resolve_instructions` directly with stubbed inputs — pure unit tests of the prompt assembly.

## Why the regression pins must pass today

| Pin | What it guards |
|-----|----------------|
| 5 | Happy path: trusted setup with rc 0 → `RunOutcome.passed`. The W6.1 prep test (`tests/prep/test_prep_fail_closed.py::test_setup_script_failure_warn_only_on_trusted_tier`) currently asserts the opposite — this is exactly what S1.2 flips. After S1.2, that prep test must move to RED (handled by the impl wave's reconciliation). Test 5 takes its place. |
| 6 | `setup_script: None` (or unset) leaves the run green; no subprocess. |
| 7 | Untrusted events still never reach `setup_script` — convention 8. |
| 17 | Empty `setup_hook_failure=""` does not inject the failure paragraph into the prompt (today's behaviour, since the string is empty). |
| 19 | Absent `setup_script_skip_reason` does not inject a skip paragraph (today, because the field doesn't reach `resolve_instructions`). |

## Source-of-truth surfaces

| Surface | File | Anchors used |
|---------|------|--------------|
| `RunOutcome` taxonomy (D3 / convention 6) | `src/mergecraft/run_outcome.py` | `RunOutcome` enum (6 values), `RUN_OUTCOME_CONCLUSION` |
| Setup-script block | `src/mergecraft/main.py:366-388` | trust check at line 368 (convention 8); current warn-only block |
| Failure wiring | `src/mergecraft/main.py:500, 560` | hardcoded `setup_hook_failure=""` — D6 wires these |
| Prompt assembly | `src/mergecraft/utils/instructions.py:329-461` | `setup_hook_failure` at line 339; branch at `:454-458` |
| Reusable kill helper (convention 9) | `src/mergecraft/utils/process_group.py` | `kill_process_group`, `wait_or_kill_process_group` |
| Redaction (convention 7) | `src/mergecraft/analyzers/redact.py:59` | `redact_secrets(text) -> str` |
| Structured `result` payload | `src/mergecraft/cli/gha_cmd.py:76` | `_structured_failure_result` |
| Test harness | `tests/support/run_main_harness.py` | `run_main_for_test` |

## What S1.2 (impl) must satisfy

1. Add `setupFailurePolicy` (`inconclusive` \| `fail` \| `warn`, default `inconclusive`) to `RepoSettings`, validated under `extra="forbid"`.
2. Rewrite `main.py:366-388` to capture the outcome into `tool_state.setup_hook_failure`, bound execution with `asyncio.wait_for`, use `start_new_session=True`, register/unregister `utils.process_group`, and apply `redact_secrets` on stderr before any consumer sees it.
3. Deduct setup elapsed time from the agent deadline at `main.py:598-603`. Default setup timeout ≤ 10 minutes, bounded even when `--notimeout` is set.
4. Pass `setup_hook_failure=setup_hook_failure` (not `""`) at both call sites `main.py:500` and `:560`.
5. Add a sibling `_setup_failure_reason` resolver at the outcome-resolution step (do **not** widen `_prep_failure_reason`); apply D10's policy.
6. Render `tool_state.setup_script_skip_reason` into the prompt in `instructions.py` (new sibling paragraph to the `setup_hook_failure` branch).
7. Add `setupFailurePolicy` and `setupTimeout` to `action.yml` and `action/inputs.py`.

## Reconciliation expectations

After S1.2 lands:
- 15 RED → green.
- `tests/prep/test_prep_fail_closed.py::test_setup_script_failure_warn_only_on_trusted_tier` flips RED (today it asserts warn-only — S1.2 inverts that).
- `docs/config-failure-policy.md` is updated; `REVIEW-CHECKS.md` gets the one-line inconclusive note; `README.md` gets the two new input rows.
