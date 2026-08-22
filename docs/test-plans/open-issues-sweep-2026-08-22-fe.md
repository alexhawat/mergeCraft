# Test plan — Batch FE (#393 antislop v1)

**Wave:** `open-issues-sweep-2026-08-22` Batch FE (W9–W12)
**Issue:** [#393](https://github.com/alexhawat/mergeCraft/issues/393)
**Branch:** `wave/repo-state-2026-08-22-sweep`

## Scope

Opt-in `antislop` catalog analyzer: YAML rules, in-process matcher for changed
Python and JS/TS files, `AnalyzerOverride.rules` / `ignore`, advisory findings only.

## Contract tests (`tests/analyzers/test_antislop.py`)

| Area | Cases |
|------|-------|
| Catalog | `get_manifest("antislop")`: `default_enabled is False`, `scope == diff`, `parser == antislop_native`, `supports_fix is False` |
| Opt-in | Default skip without override; `enabled: true` enables via `detect_enabled` |
| Finding shape | Valid taxonomy `category`; `tool == antislop`; `rule_id` prefix; evidence; `introduced_by_pr == true`; no AI/slop-score wording |
| Rules | 12 v1 rule ids load from YAML; positive + false-positive fixture per rule |
| Overrides | Per-rule `off`; path `ignore` glob |
| In-process | `IN_PROCESS_ANALYZER_IDS` includes `antislop`; `run_adapter` hook fires on fixture |

## Validation commands

```bash
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/analyzers/test_antislop.py -q
make lint && make typecheck && make catalog-check
make docs
```

## Out of scope (v1)

AI-authorship claims, slop scores, fix mode, Go/Rust packs, third-party scanner wiring.
