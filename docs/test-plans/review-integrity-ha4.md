# PR HA4 — class-derived agent toolsets — test plan (HA4.1)

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md`, **PR HA4**
Worktree: `mergecraft-ha4-role-permissions` @ `wave/ha4-role-permissions`

Locked decisions: **D14** (tool class is a new `ToolSpec` field, ten closed
values; role toolsets derive from class filters; `mutates` keeps existing
uses), **D15** (Codex prose-only subagents are recorded, not fixed).

## xfail schedule

All cross-wave markers are **non-strict** (`strict=False`) — the repo sets
`xfail_strict = true` globally. Reason prefix: `green after HA4.2: tool classes`.

| Test | Marker | Status at HA4.1 |
|------|--------|-----------------|
| `tests/mcp/test_tool_classes.py` (9 tests) | `green after HA4.2: tool classes` | **RED** |
| `tests/agents/test_codex_subagent_parity.py::test_codex_subagent_degradation_is_declared` | same | **RED** (D15) |
| `tests/mcp/test_tool_classes.py::test_deny_list_derivation_is_not_empty` | none | **green today** — regression pin on `agents/gates.py`'s empty-list guard |

**Acceptance (HA4.1):** 11 collected; 1 pass; 10 xfail. Zero collection errors.

## Target API HA4.2 must satisfy

`tool_class: ToolClass` on `ToolSpec` (`src/mergecraft/mcp/shared.py`) — required,
no default. `ToolClass` is a closed `StrEnum` of exactly these ten values:

`scope`, `repository-read`, `analysis`, `verification`, `review-read`,
`review-write`, `github-mutation`, `repository-mutation`, `shell`,
`terminal-protocol`.

Builders in `src/mergecraft/mcp/server.py`:

| Role | Builder | Allowed classes |
|------|---------|-----------------|
| orchestrator | `build_orchestrator_tools` | all except `repository-mutation` when `push` is restricted |
| reviewer | `build_reviewer_tools` | `scope`, `repository-read`, `analysis`, `review-read` |
| verifier | `build_verifier_tools` | `repository-read`, `analysis`, `verification` |

Deny lists in `src/mergecraft/agents/gates.py` derive from the complement of
the role's allowed classes. `verifier_denied_tool_names` stops delegating to
`subagent_denied_tool_names`.

D15 symbol: `CODEX_SUBAGENT_DEGRADATION` on `src/mergecraft/agents/codex.py`,
with `.kind == "prose-only"` and `.toolset_parity is False`.

## Contract → coverage matrix

Assertions build real toolsets through `mcp/server.py` and inspect `ToolSpec`
objects. No source greps.

### `tests/mcp/test_tool_classes.py` — 10 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_every_registered_tool_declares_a_class` | unit | happy + error (unclassified) | Every `ToolSpec` from `build_orchestrator_tools` / `build_common_tools` has a `ToolClass` member; the enum is exactly the ten closed values |
| 2 | `test_reviewer_receives_no_mutation_tool` | integration | happy + guard-deletion | H4: `build_reviewer_tools` returns only reviewer-allowed classes; no mutation class (`github-mutation`, `repository-mutation`, `shell`, `terminal-protocol`, `review-write`) |
| 3 | `test_verifier_receives_no_mutation_tool` | integration | happy + guard-deletion | Same for `build_verifier_tools` against verifier-allowed classes |
| 4 | `test_reviewer_and_verifier_toolsets_differ` | integration | happy (H4 core) | Name sets and class sets differ; reviewer has `scope` and not `verification`; verifier has `verification` and not `scope` |
| 5 | `test_no_read_only_role_receives_terminal_protocol` | integration | edge (VP1 may be absent) | H5: neither read-only role receives `terminal-protocol`. If `submit_review_verdict` is unregistered, the intersection is empty and the assertion still holds; if it is registered, it must not appear in either toolset |
| 6 | `test_no_read_only_role_receives_github_mutation` | integration | guard-deletion | Orchestrator *does* carry `github-mutation` tools; deleting the class filter and handing that surface to a read-only role fails this test |
| 7 | `test_no_read_only_role_receives_shell` | integration | guard-deletion | Restricted-shell runs register a `shell`-class tool on the orchestrator; read-only roles still receive none (`shell` / `kill_background` absent by name too) |
| 8 | `test_orchestrator_receives_only_policy_allowed_classes` | integration | happy + edge | `push=restricted` → no `repository-mutation`; `push=enabled` → `repository-mutation` is present (otherwise the restricted exclusion is vacuous) |
| 9 | `test_shell_disabled_run_exposes_no_execution_tool` | integration | edge | `shell=disabled` → no `shell`-class tool on orchestrator, reviewer, or verifier |
| 10 | `test_deny_list_derivation_is_not_empty` | unit | regression pin | `subagent_denied_tool_names` and `verifier_denied_tool_names` are non-empty subsets of the registered orchestrator names. Fails if the empty-list guard in `agents/gates.py` is deleted and derivation returns `[]` |

### `tests/agents/test_codex_subagent_parity.py` — 1 test

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 11 | `test_codex_subagent_degradation_is_declared` | unit | D15 | `CODEX_SUBAGENT_DEGRADATION.kind == "prose-only"` and `.toolset_parity is False`. A harness-by-model benchmark that treated Codex subagents as at parity with class-filtered Claude/OpenCode subagents would fail this pin |

## Imports of not-yet-existing symbols

`ToolClass`, `build_reviewer_tools`, `build_verifier_tools`, and
`CODEX_SUBAGENT_DEGRADATION` are imported **inside test bodies** (or helpers
those bodies call) so collection succeeds before HA4.2.

## Known follow-up (HA4.2 reconciliation)

`tests/agents/test_verifier.py::test_verifier_deny_list_derived_from_mutates_non_empty`
currently asserts `verifier_denied_tool_names(ctx) == subagent_denied_tool_names(ctx)`
— that equality **is** H4's defect. After HA4.2 the lists must differ; only
test-creator may drop that equality pin (keep the non-empty / `push_branch`
asserts). Do not treat that existing test as a HA4.1 deliverable.

## Status

HA4.1 RED authored. Verified via:

```
uv run pytest --collect-only -q tests/mcp/test_tool_classes.py \
  tests/agents/test_codex_subagent_parity.py
# -> 11 tests collected

uv run pytest -q tests/mcp/test_tool_classes.py \
  tests/agents/test_codex_subagent_parity.py
# -> 1 passed, 10 xfailed
```

`make lint` + `make typecheck` clean. No `src/` edits.
