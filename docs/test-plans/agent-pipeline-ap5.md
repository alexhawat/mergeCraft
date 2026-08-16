# PR AP5 — promote 20 themed lenses from prose to registry — test plan (AP5.1)

Wave plan: `.ignorelocal/03-agent-pipeline-wave-plan.md` (PR AP5)
Worktree: `../mergecraft-agent-pipeline` @ `feature/agent-pipeline-ap5`
Authoring wave: **AP5.1** (tests-first). Implementation: **AP5.2**.
xfail-reconciliation: **post-AP5.2** (complete).

Locked decisions: **D11** (six originally-dropped lenses ship with the other 14 —
`impact`, `research-validated-assumptions`, `user-journey`, `operational-readiness`,
`integration & cross-cutting`, `holistic` must not regress review coverage),
**convention 6** (registry selects; no fixed specialist cap — routing recall gate).

## xfail schedule

| Test file | Tests | Marker | Status |
|-----------|-------|--------|--------|
| `tests/agents/test_lenses.py` | 9 | — | **GREEN** |

**Acceptance (post-AP5.2 reconciliation):** 9 collected; 9 pass. `make lint` +
`make typecheck` clean. Rubric preservation compares against
`tests/_fixtures/ap5_starter_menu_rubrics.json` (starter-menu prose frozen at AP5.1;
`Review.TEMPLATE` no longer embeds bullets after AP5.2).

## Target API AP5.2 must satisfy

### `src/mergecraft/agents/lenses/<id>.py` (new, one per lens)

Each module exports a frozen `LensDefinition` (name may vary) with:

| Field | Contract |
|-------|----------|
| `lens_id` | Stable slug (`security`, `copy-vs-code`, `schema-migration`, …) |
| `title` | Human display title (starter-menu prose title where applicable) |
| `rubric` | Preserved starter-menu prose — byte-identical to `tests/_fixtures/ap5_starter_menu_rubrics.json` for the 13 prompt lenses |
| `triggers` | `LensTriggers` (`categories`, `minRiskBand`) for AP4 routing intersection |
| `required_evidence` | Non-empty tuple of evidence kinds the lens expects |
| `tool_classes` | Per-lens `frozenset[ToolClass]` — security includes `ANALYSIS`; copy-vs-code includes `REPOSITORY_READ` without `ANALYSIS` |

### `src/mergecraft/agents/lenses/__init__.py` (new)

| Symbol | Contract |
|--------|----------|
| `load_lens_catalog()` | Returns catalog with `prompt_lens_ids`, `backlog_lens_ids`, `all_lens_ids` |
| `get_lens(lens_id)` | Returns bundled `LensDefinition`; raises on unknown id |
| `build_subsystem_lens(lens_id)` | Synthesizes orchestrator-invented subsystem lenses (e.g. `auth`) with discovery shape; **not** in `all_lens_ids` |
| `PROMPT_LENS_IDS` / `BACKLOG_LENS_IDS` | Frozen sets matching D11 + backlog table |

Thirteen **prompt lenses** (D11 starter menu):

`correctness`, `data-integrity`, `impact`, `copy-vs-code`,
`research-validated-assumptions`, `security`, `privilege-drop-ordering`,
`user-journey`, `operational-readiness`, `integration`, `test-integrity`,
`performance`, `holistic`

Seven **backlog lenses**:

`api-compatibility`, `concurrency`, `schema-migration`, `dependency-build`,
`policy`, `requirements`, `cross-repo`

### `src/mergecraft/agents/registry.py` (extend)

`load_registry` merges bundled lens bindings from `agents/lenses/` into the
default roster. Every lens binding has non-null `triggers` (AP4 validation).

### `src/mergecraft/cli/lens_cmd.py` (new)

`lens list|show|test` registered on `mergecraft.cli.app`.

| Verb | Contract |
|------|----------|
| `lens list` | Lists bundled lens ids + titles |
| `lens show <id>` | Prints rubric, triggers, required evidence, tool classes |
| `lens test <id> --diff <path>` | Runs one lens in isolation against a diff fixture; exit 0 on success |

### `src/mergecraft/modes/Review.py` (modify)

Step 4 starter menu bullets are **removed** from `TEMPLATE`. The prompt references
the lens registry / catalog instead (no double source of truth). Rubric text moves
into lens modules unchanged — not rewritten (out-of-scope guard).

## Contract → coverage matrix

### `tests/agents/test_lenses.py` — 9 tests

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_all_thirteen_prompt_lenses_have_registry_entries` | integration | D11 happy | All 13 starter-menu ids in catalog + registry with triggers |
| 2 | `test_seven_backlog_lenses_have_entries` | integration | happy | Seven backlog ids in catalog + registry |
| 3 | `test_subsystem_lenses_need_no_entry` | unit | edge | `auth` not in catalog; `build_subsystem_lens("auth")` has rubric + triggers + evidence |
| 4 | `test_each_lens_declares_triggers_rubric_and_required_evidence` | unit | data integrity | Every bundled lens has triggers, rubric, required_evidence |
| 5 | `test_each_lens_has_its_own_toolset` | unit | guard-deletion | Security ≠ copy-vs-code toolsets; security has `ANALYSIS`; copy has read without analyzers |
| 6 | `test_lens_rubric_text_is_preserved_from_the_prompt` | unit | byte preservation | Rubric == `ap5_starter_menu_rubrics.json` per prompt lens |
| 7 | `test_prompt_no_longer_duplicates_the_menu` | functional | de-duplication | No starter-menu bullets in `TEMPLATE`; registry reference present |
| 8 | `test_lens_test_verb_runs_one_lens_in_isolation` | functional/E2E | CLI | `lens test security --diff` exits 0 with lens output |
| 9 | `test_review_coverage_does_not_regress` | integration | recall gate | Eval-shaped baseline (`tests/_fixtures/ap5_routing_recall_baseline.json`) — mean recall ≥ `min_recall` |

## Imports of not-yet-existing symbols

`mergecraft.agents.lenses` and `mergecraft.cli.lens_cmd` symbols are imported
**inside test bodies** (or helpers those bodies call) so collection succeeds before
AP5.2.

## Baseline fixtures

`tests/_fixtures/ap5_routing_recall_baseline.json` — eight eval-shaped routing
cases with `expected_lens_ids` and `min_recall: 1.0`. Captures pre-refactor
routing intent; AP5.2 must not drop recall on this corpus.

`tests/_fixtures/ap5_starter_menu_rubrics.json` — frozen starter-menu rubric
prose for the 13 prompt lenses (captured before AP5.2 removed bullets from
`Review.TEMPLATE`).

## Status

AP5.1 RED suite authored; AP5.2 implementation landed; post-AP5.2 xfail
reconciliation complete — all nine tests GREEN.
