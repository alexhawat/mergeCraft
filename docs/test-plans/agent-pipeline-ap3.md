# PR AP3 — structured handoff, model diversity, ensemble dispatch — test plan (AP3.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP3)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline-ap3`
Authoring wave: **AP3.1** (tests-first). Implementation: **AP3.2**.
xfail-reconciliation: **post-AP3.2**.

Locked decisions: **D6** (structure the hand-off, not the reasoning — free-form
discovery, typed ``AgentFinding`` emission at the boundary), **D7** (ensembles
never include the orchestrator; ``ensemble`` / ``shadow`` for discovery and
verification only), dispatch modes ``single`` (default), ``ensemble``, ``shadow``
on ``AgentBinding``, model diversity (verification must not share the authoring
model family — generalizes #45), shadow reuses ``evidence/shadow.py``
predict/record/disagree machinery.

## xfail schedule

| Test file | Tests | Marker | Status |
|-----------|-------|--------|--------|
| `tests/agents/test_structured_handoff.py` | 3 | — | **GREEN** |
| `tests/agents/test_model_diversity.py` | 2 | — | **GREEN** |
| `tests/agents/test_ensemble.py` | 6 | — | **GREEN** |

**Acceptance (post-AP3.2):** 11 collected; 11 passed; 0 xfail. `make lint` + `make typecheck` clean.

## Target API AP3.2 must satisfy

### `src/mergecraft/agents/structured_handoff.py` (new)

| Symbol | Contract |
|--------|----------|
| `SpecialistHandoff` | Dataclass/model: ``reasoning`` (prose) + ``findings: list[AgentFinding]`` |
| `parse_specialist_handoff(raw)` | Split prose from ``---typed-findings---`` tail; validate ``AgentFinding`` rows |
| `build_specialist_dispatch_prompt(binding)` | Discovery brief — **no** finding schema, ``set_output``, or JSON schema (D6) |
| `verification_plan_from_handoff(handoff, *, budget)` | Bridge to ``plan_agent_verifications`` |

Default reviewer binding sets ``output_schema == "mergecraft.agent_finding"``.

### `src/mergecraft/agents/model_diversity.py` (new)

| Symbol | Contract |
|--------|----------|
| `ModelDiversityViolation` | Raised when verification shares the authoring provider family |
| `assert_verification_diverse(authoring_slug, verification_slug)` | Guard — same family is rejected (#45 generalized) |
| `resolve_diverse_verification_model(authoring_slug, *, registry, settings)` | Pick a verifier slug in a different family |
| `enforce_policy_for_harness(registry, *, settings, harness)` | Harness-agnostic policy check (`claude`, `opencode`, `codex`, …) |

### `src/mergecraft/agents/ensemble.py` (new)

| Symbol | Contract |
|--------|----------|
| `EnsembleRun` / `ModelRun` | Per-model findings from one binding |
| `plan_ensemble_models(binding, *, settings)` | Two distinct slugs from the binding chain |
| `run_ensemble_dispatch(binding, *, registry, settings, execute)` | Fan-out dispatch respecting binding budget (CC3) |
| `reconcile_ensemble(run)` | Agreement → ``confidence_boost``; disagreement → ``judge_dispatch`` |
| `run_shadow_dispatch(binding, *, registry, settings, execute, record_path)` | Primary acted; shadow recorded via ``record_shadow_prediction`` |
| `validate_ensemble_eligible(binding)` | **D7** — raises ``EnsembleCardinalityError`` for orchestrator |
| `EnsembleCardinalityError` | Cardinality guard when orchestrator is ensembled |

## Contract → coverage matrix

### `tests/agents/test_structured_handoff.py` — 3 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_specialist_returns_typed_findings` | unit + integration | D6 happy | Prose preserved; typed tail → ``AgentFinding`` via ``output_schema`` |
| 2 | `test_free_form_discovery_is_not_constrained` | unit | D6 guard-deletion | Discovery prompt lacks schema / ``set_output`` / ``"findings"`` |
| 3 | `test_typed_findings_feed_the_verifier_directly` | integration | happy | ``verification_plan_from_handoff`` queues verifier dispatches with rubric brief |

### `tests/agents/test_model_diversity.py` — 2 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 4 | `test_verification_never_runs_on_the_authoring_family` | integration | #45 generalized | Same-family override rejected; diverse resolver succeeds |
| 5 | `test_policy_holds_across_harnesses` | integration | happy | ``enforce_policy_for_harness`` for `claude`, `opencode`, `codex` |

### `tests/agents/test_ensemble.py` — 6 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 6 | `test_ensemble_runs_the_same_agent_on_two_models` | integration | happy | ``dispatch: ensemble`` runs two chain slugs |
| 7 | `test_agreement_raises_confidence` | unit | happy | ``reconcile_ensemble`` → ``agreement=True``, ``confidence_boost > 0`` |
| 8 | `test_disagreement_is_routed_to_the_judge` | unit | edge | Disagreement → ``judge_dispatch`` with both briefs |
| 9 | `test_shadow_model_output_is_recorded_but_never_acted_on` | integration | shadow | Shadow row on disk; ``acted_findings`` == primary only |
| 10 | `test_orchestrator_cannot_be_ensembled` | unit | D7 guard-deletion | Orchestrator → ``EnsembleCardinalityError`` |
| 11 | `test_ensemble_respects_the_agent_budget` | integration | CC3 | Total findings ≤ binding ``budget`` |

## Imports of not-yet-existing symbols

``mergecraft.agents.structured_handoff``, ``mergecraft.agents.model_diversity``, and
``mergecraft.agents.ensemble`` symbols are imported inside test bodies so
collection succeeds before AP3.2.

## Status

AP3.1 suite authored; AP3.2 implementation landed; xfail markers removed (11 passed).
