# PR AP6 — pluggable orchestrator with declarative pipeline file — test plan (AP6.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP6)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline-ap6`
Authoring wave: **AP6.1** (tests-first). Implementation: **AP6.2**.
xfail-reconciliation: **post-AP6.2** (complete).

Locked decisions: **D9** (repo-supplied pipeline is executable configuration — untrusted
sources use the operator's pipeline), **D10** (`orchestrator: llm` stays the default),
**D8** (linear step list before graphs), **convention 3** (policy authority never moves —
reaching a terminal node is not approval), **convention 7** (predicates are declarative and
non-executable).

## xfail schedule (historical)

AP6.2 markers (`strict=True`, reason `AP6.2`) were removed post-AP6.2 reconciliation.
Previously:

| Test file | Tests | Marker | Status at AP6.1 |
|-----------|-------|--------|-----------------|
| `tests/orchestrator/test_kinds.py` | 3 (all except default pin) | `strict=True`, reason `AP6.2` | **RED (xfail)** |
| `tests/orchestrator/test_pipeline_file.py` | 6 | `strict=True`, reason `AP6.2` | **RED (xfail)** |
| `tests/orchestrator/test_pipeline_trust.py` | 3 | `strict=True`, reason `AP6.2` | **RED (xfail)** |
| `tests/cli/test_pipeline_verbs.py` | 2 | `strict=True`, reason `AP6.2` | **RED (xfail)** |

`test_llm_is_the_default` was never xfailing — it pins D10 compatibility (unset config
behaves as today's LLM orchestrator).

**Acceptance (post-AP6.2 reconciliation):** 15 collected; 15 pass; 0 xfail/xpass.
`make lint` + `make typecheck` clean. Shared pipeline fixtures exposed via
`pytest_plugins` in `tests/conftest.py` so `tests/cli/` can use orchestrator fixtures.

## Target API AP6.2 must satisfy

### `src/mergecraft/config/settings.py`

| Field | Contract |
|-------|----------|
| `orchestrator` | `Literal["llm", "deterministic", "hybrid"]`, default `"llm"` (D10) |

### `src/mergecraft/orchestrator/pipeline.py` (new)

| Symbol | Contract |
|--------|----------|
| `PipelineDefinition` | Parsed step list (D8): `id`, `kind`, `when`, `fan_out`, `on_error`, `budget`, `timeout` |
| `parse_pipeline(text)` | Load YAML/JSON pipeline body |
| `validate_predicate(expr)` | Closed vocabulary over classifier/diff signals; rejects unknown ops (convention 7) |
| `PipelineValidationError` | Config errors including forbidden executable predicates |

Allowed predicate forms (non-exhaustive): `changed_paths matches`, `risk_band >=`,
`languages includes`, `analyzer_findings.severity >=`.

### `src/mergecraft/orchestrator/executor.py` (new)

| Symbol | Contract |
|--------|----------|
| `PipelineExecutor` | Walk steps in order; dispatch via AP1 `Registry`; record ran/skipped/failed per step |
| `PipelineRunResult` | `step_records`, `terminal_submission`, `orchestrator_kind`, `orchestrator_tokens`, `terminal_protocol`, `structural_approval`, `policy_verdict`, `verifier_skipped_by_repo_pipeline` |
| `StepRecord` | `step_id`, `status` (`ran` \| `skipped` \| `failed`), `skip_reason`, `dispatched_agents`, `on_error_applied` |

Terminal step must call `submit_review_verdict` / `record_validated_terminal_submission`
(convention 3). Reaching the terminal node must not imply `decide_approval()` success.

### `src/mergecraft/orchestrator/trust.py` (new)

| Symbol | Contract |
|--------|----------|
| `resolve_effective_pipeline(...)` | Trusted tier honours repo pipeline; untrusted uses operator pipeline with recorded skip reason (D9, mirrors `setup_script` gate) |

### `src/mergecraft/cli/pipeline_cmd.py` (new)

| Command | Contract |
|---------|----------|
| `pipeline lint` | Validate pipeline file + registry agent refs |
| `pipeline show` | Preview steps for a diff (run/skip per `when`) |
| `pipeline explain` | (impl detail — registered alongside lint/show) |

Registered on `mergecraft.cli.app` as `pipeline`.

## Contract → coverage matrix

### `tests/orchestrator/test_kinds.py` — 4 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_llm_is_the_default` | unit | compatibility pin | **passes today** — D10 unset/default `llm` |
| 2 | `test_deterministic_kind_runs_the_pipeline` | integration | happy | Deterministic executor walks steps; zero orchestrator tokens |
| 3 | `test_all_kinds_terminate_through_the_same_verdict_protocol` | integration | convention 3 | `llm`, `deterministic`, `hybrid` all record `submit_review_verdict` |
| 4 | `test_reaching_a_terminal_node_is_not_approval` | integration | guard-deletion | Terminal node ≠ `decide_approval` success |

### `tests/orchestrator/test_pipeline_file.py` — 6 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 5 | `test_steps_execute_in_order` | integration | happy | Declaration order preserved |
| 6 | `test_conditional_step_is_skipped_with_a_recorded_reason` | integration | edge | False `when` → skipped + reason |
| 7 | `test_fan_out_dispatches_registry_agents` | integration | happy | `fan_out` dispatches listed registry agents |
| 8 | `test_on_error_policies_apply` | integration | error | `continue` vs `fail` honoured |
| 9 | `test_predicate_vocabulary_is_closed` | unit | convention 7 | Allowed predicates parse; unknown ops rejected |
| 10 | `test_predicate_cannot_execute_code` | unit | security | `eval`/shell/import predicates rejected |

### `tests/orchestrator/test_pipeline_trust.py` — 3 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 11 | `test_untrusted_source_pipeline_is_ignored` | integration | D9 | Untrusted tier skips repo pipeline |
| 12 | `test_untrusted_pipeline_cannot_skip_the_verifier` | integration | attack | Hostile pipeline cannot omit verifier |
| 13 | `test_operator_pipeline_is_used_instead` | integration | happy | Operator pipeline replaces repo file |

### `tests/cli/test_pipeline_verbs.py` — 2 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 14 | `test_pipeline_lint_rejects_a_missing_agent_id` | functional | error | Unknown agent ref fails lint |
| 15 | `test_pipeline_show_previews_steps_for_a_diff` | functional | happy | Show previews run/skip per diff |

## Imports of not-yet-existing symbols

`mergecraft.orchestrator.*` and `mergecraft.cli.pipeline_cmd` symbols are imported
**inside test bodies** so collection succeeds before AP6.2.

## Status

AP6.1 RED suite authored; AP6.2 implementation green; xfail markers removed
post-AP6.2 reconciliation (AP6.1.5).

### AP6.1.5 reconciliation notes

- `test_pipeline_lint_rejects_a_missing_agent_id` also asserts on
  `result.exception` — CliRunner captures the unknown-agent `ValueError` rather
  than printing it to stdout/stderr.
- Shared pipeline fixtures registered via `pytest_plugins` in `tests/conftest.py`.
