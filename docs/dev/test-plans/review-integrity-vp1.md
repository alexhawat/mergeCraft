# Review integrity VP1 — `submit_review_verdict` terminal tool — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md`
Worktree: `mergecraft-vp1-terminal-tool` @ `wave/vp1-terminal-tool`

## xfail schedule

| Wave | Test files | Marker |
|------|------------|--------|
| **VP1.2** | `tests/mcp/test_submit_review_verdict.py` (all 9) | *(markers removed 2026-08-15 after VP1.2)* |
| **VP1.2** | `tests/agents/test_agent_result_terminal_fields.py::test_fields_populate_from_tool_state` | *(markers removed 2026-08-15 after VP1.2)* |

`test_defaults_preserve_existing_behaviour` was never xfailing — it is a V2 regression pin.

### xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-15 | VP1.2 | module-level `pytestmark` on `test_submit_review_verdict.py` (9 tests) + `@pytest.mark.xfail` on `test_fields_populate_from_tool_state` | Suite is now 11/11 real passes. Direct pin added: `submit_review_verdict` is in `TERMINAL_PROTOCOL_DENIED_TOOL_NAMES` (deleting the constant/guard fails the suite). |

## Named symbols this suite pins

The plan's params model was unnamed in W0. This suite pins **`SubmitReviewVerdictParams`** in `src/mergecraft/mcp/verdict.py` (`extra="forbid"`; `verdict: Literal["approve", "request_changes"]`; `summary: str`; `findings: list[AgentFinding]`). `TerminalSubmission` is pinned on `src/mergecraft/mcp/tool_state.py` alongside `ReviewRecord` / `ApprovalRecord`. Canonical payload hash is SHA-256 of `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.

| Symbol | Module | Direct test |
|--------|--------|-------------|
| `submit_review_verdict_tool` | `mcp/verdict.py` | every execute path in `test_submit_review_verdict.py` |
| `SubmitReviewVerdictParams` | `mcp/verdict.py` | `test_unknown_field_is_rejected`, `test_invalid_verdict_enum_is_rejected`, `test_missing_required_field_is_rejected` |
| `TerminalSubmission` | `mcp/tool_state.py` | `test_valid_submission_is_recorded` |
| `ToolState.terminal_submission` | `mcp/tool_state.py` | `test_valid_submission_is_recorded` |
| `ToolState.terminal_submission_conflict` | `mcp/tool_state.py` | `test_second_conflicting_submission_is_rejected` |
| `AgentFinding` (D3, no parallel type) | `agents/verifier.py` | `test_findings_use_agent_finding_shape` |
| `AgentResult.terminal_submission_received` | `agents/shared.py` | both tests in `test_agent_result_terminal_fields.py` |
| `AgentResult.terminal_submission_id` | `agents/shared.py` | `test_fields_populate_from_tool_state` |
| `AgentResult.diagnostics` | `agents/shared.py` | `test_fields_populate_from_tool_state` |
| `finalize_agent_result` | `agents/post_run.py` | `test_fields_populate_from_tool_state` |
| `build_orchestrator_tools` / `build_common_tools` | `mcp/server.py` | `test_tool_is_registered_for_orchestrator_only` |
| `subagent_denied_tool_names` / `verifier_denied_tool_names` | `agents/gates.py`, `agents/verifier.py` | `test_tool_is_in_subagent_deny_list` |
| `TERMINAL_PROTOCOL_DENIED_TOOL_NAMES` | `agents/gates.py` | `test_tool_is_in_subagent_deny_list` (deleting the constant fails the suite) |

## Contract matrix

| Decision | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| VP1 tool records a typed submission | Functional | Happy: well-formed `approve` + empty findings lands `TerminalSubmission` with id, hash, `submitted_at` | `test_valid_submission_is_recorded` |
| extra="forbid" | Unit + functional | Edge/error: unrecognized key is `ValidationError` on the params model **and** `is_error` on the tool; nothing is recorded | `test_unknown_field_is_rejected` |
| Verdict enum | Unit + functional | Error: `"lgtm"` rejected on the model and the tool | `test_invalid_verdict_enum_is_rejected` |
| Required fields | Unit + functional | Error: absent `summary` / `verdict` (parametrized) | `test_missing_required_field_is_rejected` |
| **D3** reuse `AgentFinding` | Integration | Happy: fingerprint + `identity()` survive round-trip; stored finding is an `AgentFinding` instance | `test_findings_use_agent_finding_shape` |
| **D4** identical resubmit | Functional | Happy/edge: same payload hash returns the original id; still one record; conflict flag stays false | `test_second_identical_submission_is_idempotent` |
| **D4** conflicting resubmit | Functional | Error: differing payload is an error, `terminal_submission_conflict` is true, original id remains | `test_second_conflicting_submission_is_rejected` |
| Orchestrator-only registration | Integration | Happy: real `build_orchestrator_tools` includes the name; `build_common_tools` does not; `mutates is False` | `test_tool_is_registered_for_orchestrator_only` |
| Deny lists (mutates=False still denied) | Integration | Guard: name is in `TERMINAL_PROTOCOL_DENIED_TOOL_NAMES` and both `subagent_denied_tool_names` and `verifier_denied_tool_names` | `test_tool_is_in_subagent_deny_list` |
| **V2** AgentResult defaults | Unit | Regression: `AgentResult(success=True)` still constructs; `terminal_submission_received` getattr-defaults `False` | `test_defaults_preserve_existing_behaviour` |
| Finalize copies tool state | Integration | Happy: after a recorded submission, `finalize_agent_result` sets `terminal_submission_received=True` and the id | `test_fields_populate_from_tool_state` |

Registration and deny-list tests build the real toolsets from `mcp/server.py` and assert on `ToolSpec.name`. They do not grep source.

## RED acceptance (VP1.1)

11 collected; 1 passes (`test_defaults_preserve_existing_behaviour`); 10 xfail pending VP1.2. Zero collection errors. `make lint` and `make typecheck` clean. Product code is not edited in this wave.

## Reconciliation (post-VP1.2)

11 collected; 11 passed; 0 xfail; 0 xpass. `TERMINAL_PROTOCOL_DENIED_TOOL_NAMES` now has a direct `tests/` reference. VP1 Final checkboxes are not flipped here.
