# PR HA4 — class-derived agent toolsets — test plan (HA4.1)

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md`, **PR HA4**
Worktree: `mergecraft-ha4-role-permissions` @ `wave/ha4-role-permissions`

Locked decisions: **D14** (tool class is a new `ToolSpec` field, ten closed
values; role toolsets derive from class filters; `mutates` keeps existing
uses), **D15** (Codex prose-only subagents are recorded, not fixed).

## xfail schedule

All cross-wave markers were **non-strict** (`strict=False`) — the repo sets
`xfail_strict = true` globally. Reason prefix: `green after HA4.2: tool classes`.

| Test | Marker | Status at HA4.1 | Status after HA4.2 reconciliation |
|------|--------|-----------------|-----------------------------------|
| `tests/mcp/test_tool_classes.py` (9 tests) | `green after HA4.2: tool classes` | **RED** | **cleared — real passes** |
| `tests/agents/test_codex_subagent_parity.py::test_codex_subagent_degradation_is_declared` | same | **RED** (D15) | **cleared — real pass** |
| `tests/mcp/test_tool_classes.py::test_deny_list_derivation_is_not_empty` | none | **green today** | still a real pass |
| `tests/mcp/test_tool_classes.py::test_repository_mutation_class_for_push` | none | n/a (added at reconciliation) | **green** — direct pin |

**Acceptance (HA4.1):** 11 collected; 1 pass; 10 xfail. Zero collection errors.

## HA4.2 xfail-reconciliation

HA4.2 (`cd4cace`) satisfied the class-derived toolset contracts. This pass
removed every `_HA42` / `green after HA4.2: tool classes` marker so the suite
is real passes (not XPASS). `test_deny_list_derivation_is_not_empty` was never
xfailed.

Direct pins added so deleting the guard fails the suite:

- `repository_mutation_class_for_push` — `push="enabled"` → `ToolClass`
  repository-mutation; `push="restricted"` → github-mutation.
- `CodexSubagentDegradation` — `isinstance` of `CODEX_SUBAGENT_DEGRADATION`
  plus field names `{kind, toolset_parity}`.
- `_denied_tool_names_for_allowed_classes` is a private helper and is **not**
  pinned.

**Acceptance (post HA4.2 reconciliation):** 12 collected; 12 passed; 0 xfail;
0 xpass; 0 fail.

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
typed as `CodexSubagentDegradation`, with `.kind == "prose-only"` and
`.toolset_parity is False`.

## Contract → coverage matrix

Assertions build real toolsets through `mcp/server.py` and inspect `ToolSpec`
objects. No source greps.

### `tests/mcp/test_tool_classes.py` — 11 tests

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
| 9 | `test_repository_mutation_class_for_push` | unit | guard-deletion | Direct pin of `repository_mutation_class_for_push`: `push="enabled"` → `ToolClass.REPOSITORY_MUTATION`; `push="restricted"` → `ToolClass.GITHUB_MUTATION` |
| 10 | `test_shell_disabled_run_exposes_no_execution_tool` | integration | edge | `shell=disabled` → no `shell`-class tool on orchestrator, reviewer, or verifier |
| 11 | `test_deny_list_derivation_is_not_empty` | unit | regression pin | `subagent_denied_tool_names` and `verifier_denied_tool_names` are non-empty subsets of the registered orchestrator names. Fails if the empty-list guard in `agents/gates.py` is deleted and derivation returns `[]` |

### `tests/agents/test_codex_subagent_parity.py` — 1 test

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 12 | `test_codex_subagent_degradation_is_declared` | unit | D15 | `isinstance(CODEX_SUBAGENT_DEGRADATION, CodexSubagentDegradation)`; fields `{kind, toolset_parity}`; `.kind == "prose-only"` and `.toolset_parity is False`. A harness-by-model benchmark that treated Codex subagents as at parity with class-filtered Claude/OpenCode subagents would fail this pin |

## Imports of not-yet-existing symbols

`ToolClass`, `build_reviewer_tools`, `build_verifier_tools`,
`CODEX_SUBAGENT_DEGRADATION`, `CodexSubagentDegradation`, and
`repository_mutation_class_for_push` are imported **inside test bodies** (or
helpers those bodies call) so collection succeeded before HA4.2. After
reconciliation they remain in-body imports; that is style, not a remaining
xfail.

## Known follow-up (HA4.2 reconciliation)

`tests/agents/test_verifier.py::test_verifier_deny_list_derived_from_mutates_non_empty`
currently asserts `verifier_denied_tool_names(ctx) == subagent_denied_tool_names(ctx)`
— that equality **is** H4's defect. After HA4.2 the lists must differ; only
test-creator may drop that equality pin (keep the non-empty / `push_branch`
asserts). Do not treat that existing test as a HA4.1 deliverable. Not in
scope for this reconciliation pass.

## Status

HA4.2 xfail-reconciliation complete. Verified via:

```
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/mcp/test_tool_classes.py \
  tests/agents/test_codex_subagent_parity.py -q
# -> 12 passed; 0 xfail; 0 xpass; 0 fail
```

`make lint` + `make typecheck` clean. No `src/` edits.
