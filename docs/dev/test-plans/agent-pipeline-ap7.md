# PR AP7 — declared decision nodes for hybrid orchestration — test plan (AP7.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP7)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline-ap7`
Authoring wave: **AP7.1** (tests-first). Implementation: **AP7.2**.
xfail-reconciliation: **post-AP7.2**.

Locked decisions: **convention 3** (policy authority never moves — decision nodes
route the pipeline but only `decide_approval()` decides the verdict),
**D8** (linear step list extended with `decision` kind), **D10** (`hybrid` is
shipped as capability, not default), AP3 typed handoff boundary, AP6 pipeline
executor and closed predicate vocabulary.

## xfail schedule

| Test file | Tests | Marker | Status |
|-----------|-------|--------|--------|
| `tests/orchestrator/test_decision_nodes.py` | 7 | — | **GREEN (AP7.1.5)** |

**Acceptance (AP7.1.5):** 7 collected; 7 pass; 0 xfail. `make lint` + `make typecheck` clean.

## Target API AP7.2 must satisfy

### `src/mergecraft/orchestrator/decisions.py` (new)

| Symbol | Contract |
|--------|----------|
| `DecisionNodeKind` | `triviality_gate`, `lens_selection`, `finding_disposition` |
| `TrivialityAnswer` | `outcome: Literal["trivial", "not_trivial"]`, `reason: str` |
| `LensSelectionAnswer` | `lens_ids: tuple[str, ...]` — each id resolves via `resolve_agent_ref` |
| `FindingDispositionAnswer` | `verdict: Literal["keep", "withdraw", "escalate", "needs_verification"]` — closed routing enum, **not** terminal `approve` / `request_changes` |
| `DecisionSchemaError` | Raised when structured output is outside the schema (fail closed) |
| `StructuredDecisionClient` | Protocol: single `complete_structured(schema_id=..., context=...)` call |
| `run_decision_node(kind, *, client, **context)` | Typed single call — not a full agent loop |
| `DecisionEvalCase` | Isolated fixture: `kind`, `inputs`, `expected_answer` |
| `decision_eval_cases()` | One self-contained eval case per decision kind (file 4 integration) |
| `evaluate_decision_case(case, *, answer)` | Score one decision in isolation for eval replay |

### `src/mergecraft/orchestrator/pipeline.py` (extend)

| Symbol | Contract |
|--------|----------|
| `PipelineStepKind.decision` | New step kind alongside `agent`, `terminal`, `fan_out` |
| `PipelineStep.decision` | Decision node id (`triviality_gate`, …) |
| Predicate vocabulary | Extend closed `when` expressions with `decision.<id> is trivial` / `is not_trivial` |

### `src/mergecraft/orchestrator/executor.py` (extend)

| Symbol | Contract |
|--------|----------|
| `PipelineExecutor(..., decision_client=...)` | Hybrid path invokes decision nodes at `kind: decision` steps |
| `PipelineRunResult.decision_answers` | Map of `DecisionNodeKind` → typed answer for routing + eval |
| `decision_overrides` kwarg on `run()` | Test seam to inject stub clients per decision kind |

Hybrid routing: the model (via structured-output client) **answers**; the
executor **decides** the next step from the typed answer and pipeline `when`
predicates — prose in `reason` must not change routing.

Triviality behaviour (runtime proof in AP7 Final): doc-typo diff → skip
`review`/`verify`; billing one-liner → run full specialist path.

## Contract → coverage matrix

### `tests/orchestrator/test_decision_nodes.py` — 7 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_triviality_gate_returns_a_typed_answer` | unit | happy | `TrivialityAnswer` from single structured call |
| 2 | `test_lens_selection_returns_registry_ids` | integration | happy | `LensSelectionAnswer.lens_ids` resolve in registry |
| 3 | `test_finding_disposition_returns_a_closed_verdict` | unit | happy | Closed routing verdict; not terminal approval |
| 4 | `test_pipeline_owns_control_flow_not_the_model` | integration | guard-deletion | Typed `not_trivial` routes to review despite skip prose |
| 5 | `test_decision_node_answer_outside_the_schema_fails_closed` | unit | error | `DecisionSchemaError` on invalid outcome |
| 6 | `test_each_decision_is_independently_evaluable` | integration | file 4 | Each kind has isolated `DecisionEvalCase` + scorer |
| 7 | `test_hybrid_preserves_the_trivial_skip_behaviour` | functional | edge | Doc typo skips specialists; billing one-liner does not |

Shared fixtures: `hybrid_triviality_pipeline_yaml`, `doc_typo_diff`,
`billing_one_liner_diff`, `write_diff` in `tests/orchestrator/conftest.py`.

## Imports of not-yet-existing symbols

`mergecraft.orchestrator.decisions` symbols and extended `PipelineExecutor`
hybrid kwargs are imported **inside test bodies** so collection succeeds before
AP7.2.

## Status

AP7.1 RED suite authored; AP7.2 implementation complete; AP7.1.5 xfail
reconciliation done — all seven decision-node tests pass without markers.
