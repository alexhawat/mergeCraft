# PR AP1 — agent registry — test plan (AP1.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP1)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline`
Authoring wave: **AP1.1** (tests-first). Implementation: **AP1.2**.
xfail-reconciliation: **post-AP1.2**.

Locked decisions: **D3** (per-agent model chain defaults to run chain, reuses
`pick_runnable_slug_from_chain`), **D4** (record executed model, fail loudly when
a harness cannot express a binding), **D2** (full roster is config — only routed
agents render per run; AP1 loads defaults + overrides).

## xfail schedule

All AP1.2 markers use `strict=False` (`pyproject.toml` sets `xfail_strict = true`).
Reason prefix: `green after AP1.2`.

| Test file | Tests | Marker | Status at AP1.1 |
|-----------|-------|--------|-----------------|
| `tests/agents/test_registry.py` | 12 registry tests (all except `test_agent_chain_defaults_to_the_run_chain`) | `green after AP1.2: agent registry` | **RED (xfail)** |
| `tests/cli/test_agents_verbs.py` | 3 CLI tests | `green after AP1.2: agents CLI` | **RED (xfail)** |

`test_agent_chain_defaults_to_the_run_chain` is never xfailing — it pins today's
run-level `effective_model_chain` behaviour that AP1 defaults must preserve.

**Acceptance (AP1.1):** 16 collected; 1 pass; 15 xfail. Zero collection errors.
`make lint` + `make typecheck` clean. No `src/` edits.

## Target API AP1.2 must satisfy

`src/mergecraft/agents/registry.py` (new):

| Symbol | Contract |
|--------|----------|
| `AgentRole` | Closed enum: `orchestrator`, `reviewer`, `verifier`, `judge`, `classifier` |
| `AgentBinding` | Frozen Pydantic: `agent_id`, `role`, `lens`, `model_chain`, `prompt_id`, `prompt_version`, `tool_classes`, `budget`, `timeout_s`, `dispatch`, `output_schema` |
| `ResolvedAgentModel` | `requested_model`, `executed_model`, `recorded_model`, `dispatched_model` — executed/recorded/dispatched align (D4) |
| `AgentLimits` | `budget`, `timeout_s` from binding + config |
| `RegistryValidationError` | Raised by `Registry.validate()` |
| `load_registry(settings, repo_root)` | Defaults reproduce today; merges `.mergecraft/config.yaml` `agents:` overrides |
| `Registry.resolve_role(role)` | Returns binding for each core role |
| `Registry.resolve_tool_names(binding, ctx)` | HA4 class-filtered MCP tool **names** for the binding |
| `resolve_agent_model(binding, settings, slug_runnable=...)` | Per-agent chain via `pick_runnable_slug_from_chain`; records executed slug |
| `resolve_prompt_text(prompt_id, version=...)` | Catalog lookup — unknown id fails validation |
| `effective_agent_limits(binding, settings)` | Applies per-agent budget/timeout |

`src/mergecraft/cli/agents_cmd.py` (new): `agents list|show|set`, registered on
`mergecraft.cli.app`.

## Contract → coverage matrix

### `tests/agents/test_registry.py` — 13 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_every_role_resolves_to_a_binding` | integration | happy | All five roles resolve with model, prompt, and tool metadata |
| 2 | `test_reviewer_and_verifier_have_different_toolsets` | integration | P2 guard-deletion | Real registry builds both toolsets; name sets differ (`checkout_pr` vs `verify_agent_findings`) |
| 3 | `test_per_agent_model_chain_falls_back` | unit | P3/D3 edge | Agent-owned chain skips unavailable primary |
| 4 | `test_executed_model_is_recorded_not_requested` | unit | D4 error path | `recorded_model` is the executed fallback, not the requested head |
| 5 | `test_verifier_pin_invariant_survives_fallback` | integration | #45 | Verifier chain head is `pinned_judge_model("claude")`; after fallback, `recorded_model == dispatched_model == executed_model` |
| 6 | `test_agent_chain_defaults_to_the_run_chain` | unit | compatibility pin | **passes today** — `effective_model_chain` for a three-model config |
| 7 | `test_prompt_id_and_version_are_bound` | integration | happy | Reviewer/verifier ids resolve to `REVIEWER_SYSTEM_PROMPT` / `VERIFIER_SYSTEM_PROMPT` |
| 8 | `test_toolset_derives_from_tool_classes` | integration | HA4 | Declared `tool_classes` match `build_reviewer_tools` name/class sets |
| 9 | `test_no_read_only_agent_gets_a_terminal_protocol_tool` | integration | guard-deletion | Reviewer, verifier, classifier lack `submit_review_verdict` |
| 10 | `test_per_agent_budget_and_timeout_apply` | integration | happy + override | Config `budget` / `timeoutS` flow to binding and `effective_agent_limits` |
| 11 | `test_registry_validation_rejects_a_missing_model` | unit | error | Unknown model slug → `RegistryValidationError` |
| 12 | `test_registry_validation_rejects_an_unknown_prompt_id` | unit | error | Unknown `promptId` → `RegistryValidationError` |
| 13 | `test_registry_validation_rejects_an_unreachable_lens` | unit | error | Lens entry without registry support → `RegistryValidationError` |

### `tests/cli/test_agents_verbs.py` — 3 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 14 | `test_agents_list_shows_model_prompt_and_tools` | functional | happy | `agents list` shows role, model, prompt, tools |
| 15 | `test_agents_show_prints_the_resolved_prompt_and_exact_tool_names` | functional | happy | `agents show reviewer` prints prompt body + exact tool names |
| 16 | `test_agents_set_overrides_one_binding` | functional | happy | `agents set reviewer --model …` persists override; reload shows new chain head |

## Imports of not-yet-existing symbols

`mergecraft.agents.registry` and `mergecraft.cli.agents_cmd` symbols are imported
**inside test bodies** (or helpers those bodies call) so collection succeeds before
AP1.2.

## Status

AP1.1 RED suite authored. Pending AP1.2 implementation and xfail reconciliation.
