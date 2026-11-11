# PR DG3 — context core — test plan (DG3.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG3)
Worktree: `../mergecraft-dg3-context-core` @ `wave/dg3-context-core`
Authoring wave: **DG3.1** (tests-first). Implementation: **DG3.2**.
xfail-reconciliation: **post-DG3.2** (complete).

Locked decisions: **D5** (discovered instruction files from untrusted sources are
fenced data, never instruction bundle), **D6** (tree-sitter with generic fallback;
record reduced fidelity), **convention 4** (reproducible citations: repo + SHA +
path), **convention 6** (cache by git object SHA).

Precondition: **TS1** — `mergecraft.analyzers.trust.derive_source_trust_tier` exists.

## xfail schedule

Thirteen DG3.1 tests use `@pytest.mark.xfail(reason="green after DG3.2",
strict=False)`. Zero pass pre-DG3.2.

| Test file | Tests | Marker | Status pre-DG3.2 |
|-----------|-------|--------|------------------|
| `tests/context/test_repo_map.py` | 2 | xfail | **RED** |
| `tests/context/test_symbol_index.py` | 4 | xfail | **RED** |
| `tests/context/test_provenance.py` | 2 | xfail | **RED** |
| `tests/context/test_instruction_discovery.py` | 5 | xfail | **RED** |

**Acceptance (DG3.1):** 13 collected; 0 pass; 13 xfail. `make lint` + `make typecheck`
clean.

## Target API DG3.2 must satisfy

### `src/mergecraft/context/repo_map.py` (new)

| Symbol | Contract |
|--------|----------|
| `build_repo_map(*, repo_root, tree_sha, cache=None)` | Index packages, services, entrypoints, build config |
| `RepoMap` | `packages`, `services`, `entrypoints`, `build_config` collections with `path` / `name` |
| cache protocol | Keyed by git **tree** object SHA (convention 6) |

### `src/mergecraft/context/symbol_index.py` (new)

| Symbol | Contract |
|--------|----------|
| `index_symbols(*, repo_root, rel_path, blob_sha, cache=None)` | Return indexed symbols for one file |
| `SymbolIndexResult` | `symbols`, `backend` (`tree_sitter` \| `generic`), `fidelity` (`full` \| `reduced`), optional `fidelity_note` |
| cache protocol | Keyed by git **blob** object SHA (convention 6) |

### `src/mergecraft/context/provenance.py` (new)

| Symbol | Contract |
|--------|----------|
| `ContextItem` | `repo`, `sha`, `path`, `reason`, `text`, `token_cost`; `as_citation()` → `repo@sha:path` |
| `inspect_context(items)` | Return report with `total_tokens` and per-item `token_cost` + `path` |

### `src/mergecraft/context/instruction_discovery.py` (new)

| Symbol | Contract |
|--------|----------|
| `render_review_context(*, repo_root, trust_tier, repo, commit_sha)` | Render the review prompt section for discovered repo instructions/skills |
| discovery | Reuse `analyzers/agentsec/skill_manifest.py` enumeration (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `.cursor/rules/*.md`) |
| trusted tier | Load discovered files into `************* REPO INSTRUCTIONS *************` without fence |
| untrusted tier | Fence discovered content via `mergecraft.utils.fence`; **never** merge into instruction bundle |

Security pin: `test_untrusted_instructions_never_enter_the_instruction_bundle` asserts on
the **rendered prompt** — marker text must appear only inside
`<<<UNTRUSTED-MERGECRAFT-CONTENT` blocks, not in `REPO INSTRUCTIONS` or `STANDING
INSTRUCTIONS` sections.

## Contract → coverage matrix

### Repo map — `tests/context/test_repo_map.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_indexes_packages_services_entrypoints_and_build_config` | integration | happy | Packages, services, entrypoints, build config indexed |
| 2 | `test_map_is_cached_by_tree_sha` | unit | cache | Tree SHA cache key (convention 6) |

### Symbol index — `tests/context/test_symbol_index.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 3 | `test_indexes_symbols_for_a_supported_language` | integration | happy | Python symbols via tree-sitter |
| 4 | `test_unsupported_language_degrades_to_the_generic_fallback` | unit | edge | D6 generic backend |
| 5 | `test_reduced_fidelity_is_recorded` | unit | observability | D6 `fidelity=reduced` + note |
| 6 | `test_index_is_cached_by_blob_sha` | unit | cache | Blob SHA cache key (convention 6) |

### Provenance — `tests/context/test_provenance.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 7 | `test_every_context_item_records_repo_sha_path_and_reason` | unit | happy | Convention 4 citation fields |
| 8 | `test_context_inspect_reports_token_cost_per_item` | unit | observability | Per-item token accounting |

### Instruction discovery — `tests/context/test_instruction_discovery.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 9 | `test_trusted_repo_instructions_are_loaded` | functional | happy | G9 trusted bundle load |
| 10 | `test_untrusted_repo_instructions_are_fenced_as_data` | security | D5 | W4 fence wrapper |
| 11 | `test_untrusted_instructions_never_enter_the_instruction_bundle` | security | D5 | Rendered prompt bundle exclusion |
| 12 | `test_repo_skills_follow_the_same_gate` | security | G10/D5 | SKILL.md same gate |
| 13 | `test_injection_inside_a_discovered_instruction_file_is_not_obeyed` | security | injection | Fence neutralizes forged closer |

## Reconciliation notes

- Remove `@pytest.mark.xfail` from each test as DG3.2 greens it.
- `security-review` is blocking on DG3 Final (D5 prompt-injection boundary).
