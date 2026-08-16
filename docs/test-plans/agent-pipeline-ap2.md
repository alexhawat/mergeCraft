# PR AP2 — harness render — test plan (AP2.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP2)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline-ap2`
Authoring wave: **AP2.1** (tests-first). Implementation: **AP2.2**.
xfail-reconciliation: **post-AP2.2** (pending).

Locked decisions: **D2** (registry is config — only routed agents render per run),
**D4** (where a harness cannot express a binding, fail loudly),
**D5** (Codex degradation is declared in run metadata, not hidden).

## xfail schedule

All cross-wave markers are **non-strict** (`strict=False`). Reason prefix:
`green after AP2.2: harness render`.

| Test file | Tests | Marker | Status at AP2.1 |
|-----------|-------|--------|-----------------|
| `tests/agents/test_harness_render.py` | 6 harness-render tests | `green after AP2.2: harness render` | **RED (xfail)** |
| `tests/agents/test_harness_render.py::test_claude_agents_json_renders_from_registry` | 1 | none | **green today** — byte-identical pin |

**Acceptance (AP2.1):** 7 collected; 1 pass; 6 xfail. `make lint` + `make typecheck` clean.

## Target API AP2.2 must satisfy

`src/mergecraft/agents/harness_render.py` (new):

| Symbol | Contract |
|--------|----------|
| `HarnessRenderResult` | Frozen/dataclass: `harness`, `payload` (`str` or harness-shaped `dict`), `selected_agent_ids`, `metadata` |
| `UnrenderableBindingError` | Raised when a selected binding cannot be expressed on the target harness (D4) |
| `render_agents(registry, *, selected, harness, ctx)` | Projects only `selected` bindings (roles or agent ids) into the harness config (D2) |
| `run_manifest_metadata(result)` | Returns the metadata dict merged into `AgentResult.metadata` / evidence run manifest |

Harness-specific contracts:

| Harness | Render contract |
|---------|-----------------|
| `claude` | `payload` is byte-identical to legacy `build_agents_json()` for default reviewer+verifier |
| `opencode` | Subagent blocks include per-binding `model` (P4) |
| `codex` | Real subagent dispatch **or** `metadata["harness_degradations"]` with `kind` / `toolset_parity` (D5) |
| `gemini`, `cursor` | Subagent surface in payload **or** per-harness degradation row |

`metadata["harness_degradations"]` entries must include at least
`harness`, `kind`, `toolset_parity`, `selected_agents` so benchmarks and
evidence packets can distinguish prose-only collapse from toolset parity.

## Contract → coverage matrix

### `tests/agents/test_harness_render.py` — 7 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_claude_agents_json_renders_from_registry` | integration | compatibility pin | Registry-derived Claude JSON matches `build_agents_json()` bytes for default config + class-derived deny lists |
| 2 | `test_opencode_subagents_carry_per_agent_models` | integration | P4 | Two-model override → OpenCode subagent `model` fields match `resolve_agent_model` per binding |
| 3 | `test_codex_renders_real_subagents_or_declares_degradation` | integration | D5 | Codex payload has real subagents **or** `harness_degradations` lists `CODEX_SUBAGENT_DEGRADATION.kind` |
| 4 | `test_gemini_and_cursor_render_or_declare` | integration | D5 parity | Gemini and Cursor each render subagent surface **or** declare per-harness degradation |
| 5 | `test_unrenderable_binding_fails_loudly` | unit | D4 guard-deletion | Selecting `orchestrator` for Claude harness raises `UnrenderableBindingError` |
| 6 | `test_only_routed_agents_are_rendered` | integration | D2 | Selecting reviewer+verifier+classifier renders exactly three agents, not the full roster |
| 7 | `test_declared_degradation_reaches_the_run_manifest` | integration | D5 manifest | `run_manifest_metadata` exposes `harness_degradations`; merge into `AgentResult.metadata` preserves Codex degradation row |

## Imports of not-yet-existing symbols

`mergecraft.agents.harness_render` symbols are imported **inside test bodies**
(or under the xfail-marked tests) so collection succeeds before AP2.2.

## Status

AP2.1 RED suite authored; AP2.2 implementation pending. Six tests xfail;
`test_claude_agents_json_renders_from_registry` passes as the byte-identical
compatibility pin.
