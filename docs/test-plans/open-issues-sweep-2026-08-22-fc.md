# Open issues sweep 2026-08-22 — Batch FC test plan (#401)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md`
Worktree: `.ignorelocal/worktrees/repo-state-2026-08-22-sweep` @ `wave/repo-state-2026-08-22-sweep`
Authoring wave: **W5** (FC RED) · Implementation: **W6** (skip analyze when `dry_run`)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W6** | `test_review_dry_run_skips_run_analyzer_pipeline` | `green after W6: dry-run skips analyzer catalog (#401)` | pending — **XFAIL** |
| **W6** | `test_review_dry_run_skips_run_offline_analyze` | same | pending — **XFAIL** |
| **W6** | `test_offline_diff_review_dry_run_skips_pipeline_when_analyzers_enabled` | same | pending — **XFAIL** |
| **W6** | `test_offline_analyze_skips_pipeline_on_dry_run_when_analyzers_enabled` | same | pending — **XFAIL** |

Green guards (no xfail): `test_review_dry_run_still_materializes`, `test_review_dry_run_returns_offline_prompt`.

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| FC401a | `review --dry-run` does not call `run_analyzer_pipeline` when analyzers enabled | functional | error | `tests/cli/test_fc_dry_run_skips_analyzers.py::test_review_dry_run_skips_run_analyzer_pipeline` |
| FC401b | `review --dry-run` does not call `run_offline_analyze` when analyzers enabled | functional | error | `test_review_dry_run_skips_run_offline_analyze` |
| FC401c | `_run_offline_diff_review` dry-run skips pipeline when enabled | integration | error | `test_offline_diff_review_dry_run_skips_pipeline_when_analyzers_enabled` |
| FC401d | Offline analyze harness dry-run skips pipeline (renamed from invoke) | integration | error | `tests/offline_review/test_analyze_stage.py::test_offline_analyze_skips_pipeline_on_dry_run_when_analyzers_enabled` |
| FC401e | `--dry-run` still materializes (materialize runs first) | functional | happy | `test_review_dry_run_still_materializes` |
| FC401f | `--dry-run` returns offline review prompt (review short-circuit) | functional | happy | `test_review_dry_run_returns_offline_prompt` |
| FC401g | Engine stage order unchanged; analyze skip is inside driver (D10) | integration | design | `tests/review/test_review_engine_behavior.py::test_cli_review_drives_engine_run` (docstring; pipeline pins in FC module) |

## W5 RED evidence

- **#401** — four skip-contract tests **XFAIL** today (`run_analyzer_pipeline` / `run_offline_analyze` still run on dry-run).
- Materialize + prompt guards **GREEN** (dry-run already short-circuits review and materializes).

## Out of scope

- `ReviewEngine.run` stage order (`review/engine.py`).
- Skipping materialize on dry-run.
- `analyzers.enabled=False` path (unchanged — already skips pipeline).
