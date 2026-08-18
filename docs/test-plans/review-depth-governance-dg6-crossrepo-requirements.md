# PR DG6 — cross-repo intelligence and requirements mapping — test plan (DG6.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG6)
Worktree: `../mergecraft-dg6-crossrepo-requirements` @ `wave/dg6-crossrepo-requirements`
Authoring wave: **DG6.1** (tests-first). Implementation: **DG6.2**.
xfail-reconciliation: **post-DG6.2** (complete).

Locked decisions: **D9** (linked repos read only when authorized for this run),
**convention 4** (reproducible citations: repo + SHA + path + range),
**convention 5** (untrusted content is data, never instruction — route through
`mergecraft.utils.fence`).

Preconditions: **TS1** (source trust tiers) + **TS3** (clone hardening) from file 2;
**DG3** context base for provenance patterns.

## xfail schedule

Ten DG6.1 tests use `@pytest.mark.xfail(reason="green after DG6.2", strict=False)`.
One test passes pre-DG6.2 (fence regression pin).

| Test file | Tests | Marker | Status pre-DG6.2 |
|-----------|-------|--------|------------------|
| `tests/xrepo/test_linked_repos.py` | 3 | xfail | **RED** |
| `tests/xrepo/test_contract_index.py` | 1 | xfail | **RED** |
| `tests/xrepo/test_blast_radius.py` | 1 | xfail | **RED** |
| `tests/xrepo/test_citations.py` | 1 | xfail | **RED** |
| `tests/requirements/test_criteria.py` | 4 | xfail | **RED** |
| `tests/requirements/test_criteria.py` | 1 | none | **PASS** (fence regression) |

**Acceptance (DG6.1):** 11 collected; 1 pass; 10 xfail. `make lint` + `make typecheck` clean.

## Target API DG6.2 must satisfy

### `src/mergecraft/xrepo/linked_repos.py` (new)

| Symbol | Contract |
|--------|----------|
| `LinkedRepo` | `owner`, `name`, `commit` (pinned SHA) |
| `LinkedRepoManifest` | `repos: tuple[LinkedRepo, ...]` |
| `RunGrant` | `authorized_repos: frozenset[str]` — repo names authorized for this run (D9) |
| `LinkedRepoAccessError` | Raised when `load_linked_repo_content` targets a repo outside the grant |
| `parse_manifest(path)` | Parse `.mergecraft/linked-repos.yaml` with pinned commits |
| `load_linked_repo_content(manifest, repo, grant)` | Read linked content only when granted (D9) |
| `render_linked_repo_context(content, repo, commit, author)` | Fence linked-repo body via `mergecraft.utils.fence` (convention 5) |

### `src/mergecraft/xrepo/contract_index.py` (new)

| Symbol | Contract |
|--------|----------|
| `index_contracts(repo_root, commit_sha)` | Index OpenAPI, GraphQL, protobuf, and export symbols |
| `ContractIndex` | `openapi`, `graphql`, `protobuf`, `exports` collections with `path` / `symbol` |

### `src/mergecraft/xrepo/blast_radius.py` (new)

| Symbol | Contract |
|--------|----------|
| `ChangedContract` | `repo`, `commit`, `path`, `kind`, optional `operation_id` |
| `CrossRepoImpact` | `repo`, `reason`, optional `citation` |
| `resolve_cross_repo_dependents(changed_contracts, manifest, repo_roots)` | Map contract change → dependent linked repos |

### `src/mergecraft/xrepo/citations.py` (new)

| Symbol | Contract |
|--------|----------|
| `Citation` | `repo`, `sha`, `path`, `start_line`, `end_line` |
| `validate_citation(citation)` | Reject incomplete citations (convention 4) |
| `format_citation(citation)` | Render `repo@sha:path#Lstart-Lend` |

### `src/mergecraft/requirements/criteria.py` (new)

| Symbol | Contract |
|--------|----------|
| `Criterion` | Atomic acceptance-criteria item with stable `text` |
| `ChangeMap` | `changed_paths`, `touched_symbols` |
| `CriterionMapping` | `criterion`, `evidence_kind` (`code` \| `tests` \| `missing`), optional paths |
| `extract_acceptance_criteria(ticket_body)` | Parse checklist / AC sections into atomic items |
| `map_criteria_to_evidence(criteria, change_map)` | Map each criterion to code, tests, or missing evidence |
| `find_unimplemented_criteria(mappings)` | Return criteria with `evidence_kind=missing` |
| `detect_scope_creep(stated_intent, change_map)` | Flag paths/symbols outside stated intent |
| `render_ticket_context(...)` | Delegate ticket body to `mergecraft.utils.fence` (convention 5) |

Security pin: `test_unauthorized_repo_is_not_retrievable` asserts D9 — repos outside
`RunGrant.authorized_repos` raise `LinkedRepoAccessError`.

Fence regression: `test_ticket_text_is_data_never_instruction` passes pre-DG6.2 using
`render_untrusted(..., label="ticket_body")`; DG6.2 must preserve this via
`render_ticket_context`.

## Contract → coverage matrix

### Linked repos — `tests/xrepo/test_linked_repos.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_manifest_declares_repos_at_pinned_commits` | unit | happy | Manifest pins owner/name/commit |
| 2 | `test_unauthorized_repo_is_not_retrievable` | security | D9 | Grant boundary |
| 3 | `test_linked_repo_content_is_fenced_as_untrusted` | security | convention 5 | W4 fence wrapper |

### Contract index — `tests/xrepo/test_contract_index.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 4 | `test_openapi_graphql_protobuf_and_exports_are_indexed` | integration | happy | OpenAPI/GraphQL/proto/export surfaces |

### Cross-repo blast radius — `tests/xrepo/test_blast_radius.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 5 | `test_changed_contract_resolves_to_dependent_repos` | integration | happy | Contract change → consumer repo |

### Citations — `tests/xrepo/test_citations.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 6 | `test_every_citation_carries_repo_sha_and_location` | unit | happy | Convention 4 fields |

### Requirements criteria — `tests/requirements/test_criteria.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 7 | `test_acceptance_criteria_are_extracted_as_atomic_items` | unit | happy | AC extraction |
| 8 | `test_each_criterion_maps_to_code_tests_or_evidence` | integration | happy | Criterion ↔ evidence map |
| 9 | `test_unimplemented_criterion_is_reported` | unit | edge | Missing evidence surfaced |
| 10 | `test_scope_creep_is_detected` | unit | edge | Intent vs change map |
| 11 | `test_ticket_text_is_data_never_instruction` | security | fence regression | Convention 5 — **PASS pre-DG6.2** |
