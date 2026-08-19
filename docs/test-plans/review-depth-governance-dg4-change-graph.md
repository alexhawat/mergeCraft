# PR DG4 — change graph — test plan (DG4.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG4)
Worktree: `../mergecraft-dg4-change-graph` @ `wave/dg4-change-graph`
Authoring wave: **DG4.1** (tests-first). Implementation: **DG4.2**.
xfail-reconciliation: **post-DG4.2** (complete).

Depends on: **DG3** (`mergecraft.context` repo map, symbol index, provenance).
Integrations: **CC3** token budget (`mergecraft.utils.run_bounds.BudgetTracker`),
**convention 4** (reproducible citations on every context item).

## xfail schedule

Eight DG4.1 tests use `@pytest.mark.xfail(reason="green after DG4.2",
strict=False)`. Zero pass pre-DG4.2.

| Test file | Tests | Marker | Status pre-DG4.2 |
|-----------|-------|--------|------------------|
| `tests/context/test_call_graph.py` | 1 | xfail | **RED** |
| `tests/context/test_change_graph.py` | 3 | xfail | **RED** |
| `tests/context/test_dynamic_expansion.py` | 2 | xfail | **RED** |
| `tests/context/test_git_history.py` | 1 | xfail | **RED** |
| `tests/cli/test_context_inspect.py` | 1 | xfail | **RED** |

**Acceptance (DG4.1):** 8 collected; 0 pass; 8 xfail. `make lint` + `make typecheck`
clean.

## Target API DG4.2 must satisfy

### `src/mergecraft/context/call_graph.py` (new)

| Symbol | Contract |
|--------|----------|
| `build_call_graph(*, repo_root, tree_sha, cache=None)` | Index import, reference, and call edges over DG3 symbol index |
| `CallGraph` | `edges` collection with `kind` (`import` \| `reference` \| `call`), `caller`, `callee` |
| cache protocol | Keyed by git **tree** object SHA (convention 6) |

### `src/mergecraft/context/change_graph.py` (new)

| Symbol | Contract |
|--------|----------|
| `ChangedSymbol` | `path`, `name`, `kind` for one diff-touched symbol |
| `resolve_change_graph(*, repo_root, tree_sha, changed)` | Map changed symbols → dependents, covering tests, affected contracts |
| `ChangeGraphResult` | `dependents`, `tests`, `contracts` path/symbol collections |

### `src/mergecraft/context/dynamic_expansion.py` (new)

| Symbol | Contract |
|--------|----------|
| `expand_enclosing_scope(*, repo_root, path, symbol)` | On-demand retrieval of enclosing scope as `ContextItem` list |
| `expand_with_budget(*, repo_root, path, symbol, token_budget, budget_tracker=None)` | Expansion that stops before exceeding CC3 token budget; sets `truncated` when clipped |
| `ExpansionResult` | `items`, `truncated`, `token_cost` |

### `src/mergecraft/context/git_history.py` (new)

| Symbol | Contract |
|--------|----------|
| `targeted_blame(*, repo_root, repo, path, start_line, end_line)` | Line-level blame for review (not CI failure attribution) |
| `TargetedBlameResult` | `entries` (`commit_sha`, `line`, `author`, `text`) + `provenance` `ContextItem` |

### `src/mergecraft/cli/context_cmd.py` (new)

| Symbol | Contract |
|--------|----------|
| `mergecraft context inspect` | Report **sources**, **scope**, **provenance** citations, and **token** totals for a repo/scope |

## Contract → coverage matrix

### Call graph — `tests/context/test_call_graph.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_imports_references_and_callers_are_indexed` | integration | happy | Import, reference, and call edges indexed |

### Change graph — `tests/context/test_change_graph.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 2 | `test_changed_symbol_resolves_to_dependents` | integration | happy | Changed symbol → dependent symbols |
| 3 | `test_changed_symbol_resolves_to_covering_tests` | integration | happy | Changed symbol → covering test files |
| 4 | `test_changed_symbol_resolves_to_affected_contracts` | integration | happy | Changed symbol → affected contract files |

### Dynamic expansion — `tests/context/test_dynamic_expansion.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 5 | `test_enclosing_scope_is_retrieved_on_demand` | integration | happy | On-demand enclosing scope as provenance-backed items |
| 6 | `test_expansion_respects_the_token_budget` | unit | budget | CC3 token budget respected; `truncated=True` when clipped |

### Git history — `tests/context/test_git_history.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 7 | `test_targeted_blame_is_retrieved_with_provenance` | integration | happy | Targeted blame + convention 4 provenance |

### CLI — `tests/cli/test_context_inspect.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 8 | `test_reports_sources_scope_provenance_and_tokens` | functional | happy | `context inspect` surfaces sources, scope, provenance, tokens |

## Reconciliation notes

- Remove `@pytest.mark.xfail` from each test as DG4.2 greens it.
- DG4 Final requires `make reference-docs-check` after CLI surface lands.
