# Open issues sweep 2026-08-19e — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19e-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19e` @ `wave/open-issues-sweep-2026-08-19e`
Authoring wave: **W1** (Batch W RED — #338 four cheap flips)

W1 pins detect + catalog-check fixtures for `golangci-lint`, `clippy`, `rubocop`,
and `phpstan` (D7). W2 greens `default_enabled: auto` and applies D11 / D12 / D19.
Do **not** author Batch X/Y/Z fixtures here (W3 / W7 / W18).

All cross-wave xfails use `strict=False`. Do not use `strict=True` (`xfail_strict = true`
in `pyproject.toml`).

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_four_cheap_flips_default_enabled_auto` | `green after W2: four cheap flips default_enabled auto` | pending |
| **W2** | `test_four_cheap_flips_auto_enables_on_language_markers` | `green after W2: four cheap flips default_enabled auto` | pending |
| **W2** | `test_rubocop_auto_fires_when_config_is_present` | `green after W2: four cheap flips default_enabled auto` | pending |
| **W2** | `test_rubocop_auto_fires_when_gemfile_declares_rubocop` | `green after W2: four cheap flips default_enabled auto` | pending |
| **W2** | `test_phpstan_without_neon_runs_at_level_zero` | `green after W2: phpstan --level=0 without neon (D12)` | pending |

Detect-glob tests are **not** xfailed. If a detect block is missing `go.mod` /
`Gemfile` / `composer.json`, the test fails **before** the flip (W1.1). W2 must
add those globs when flipping the four manifests.

## Contract matrix

### W1.1 — detect language markers (D7)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| W1a | `golangci-lint` matches `go.mod` / `*.go` | unit | happy | `tests/analyzers/test_four_cheap_flips.py::test_language_marker_matches_detect_globs` |
| W1b | `clippy` matches `Cargo.toml` / `*.rs` | unit | happy | `…[clippy-Cargo.toml]` / `…[clippy-src/lib.rs]` |
| W1c | `rubocop` matches `*.rb` / `Gemfile` | unit | happy | `…[rubocop-Gemfile]` / `…[rubocop-hello.rb]` |
| W1d | `phpstan` matches `composer.json` / `*.php` | unit | happy | `…[phpstan-composer.json]` / `…[phpstan-hello.php]` |
| W1e | Unrelated / empty changed files do not match | unit | edge | `test_language_markers_do_not_match_unrelated_paths`, `test_empty_changed_files_do_not_enable_four_cheap_flips` |
| W1f | Nested paths (`pkg/hello.go`, `lib/hello.rb`, `src/hello.php`) | unit | edge | same parametrize table |

Language fixture trees (not catalog-check parser fixtures):

- `tests/analyzers/fixtures/batch-w/go/` — `go.mod`, `hello.go`
- `tests/analyzers/fixtures/batch-w/rust/` — `Cargo.toml`, `src/lib.rs`
- `tests/analyzers/fixtures/batch-w/ruby/` — `Gemfile`, `hello.rb`, `.rubocop.yml`
- `tests/analyzers/fixtures/batch-w/php/` — `composer.json`, `hello.php`, `phpstan.neon`

### D15 — catalog-check-shaped parser fixtures

Existing SARIF fixtures already satisfy `make catalog-check`. W1 pins they stay.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| D15a | Each of the four has `sarif/<id>-minimal.sarif.json` | unit | happy | `test_four_cheap_flips_have_catalog_check_sarif_fixture` |

### D11 — `rubocop` auto requires config

`auto` fires only when a RuboCop config is detected (`.rubocop.yml`, `.rubocop.yaml`,
`.rubocop.yml.dist`, or a `rubocop` key / `gem "rubocop"` in gem config). No config
→ not enabled / `unavailable`, not a 200-cop dump.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| D11a | `.rubocop.yml` / `.yaml` / `.yml.dist` → enabled after W2 | integration | happy | `test_rubocop_auto_fires_when_config_is_present` (xfail W2) |
| D11b | `Gemfile` declaring `gem "rubocop"` → enabled after W2 | integration | happy | `test_rubocop_auto_fires_when_gemfile_declares_rubocop` (xfail W2) |
| D11c | `*.rb` + Gemfile with no config → not enabled | integration | error | `test_rubocop_without_config_is_not_enabled` |
| D11d | Adapter must not emit default-cop findings without config | functional | error | `test_rubocop_without_config_skips_unavailable_not_a_cop_dump` |
| D11e | Changing `.rubocop.yml` matches detect globs today | unit | happy | `test_rubocop_detect_matches_shipped_config_glob` |

D11c/D11d pass today because `default_enabled: false` (and missing binary). After
the W2 auto flip they stay green only if D11 config detection lands.

### D12 — `phpstan` neon vs `--level=0`

If `phpstan.neon` / `phpstan.neon.dist` exists, use it. Else run with `--level=0`.
Do not invent a mergeCraft neon. ANALYZERS.md note is W2.2 (`make catalog-check`).

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| D12a | `phpstan.neon` / `.dist` match detect globs today | unit | happy | `test_phpstan_neon_globs_match_before_flip` |
| D12b | No neon → argv includes `--level=0` | integration | happy | `test_phpstan_without_neon_runs_at_level_zero` (xfail W2) |
| D12c | Neon present → do not force `--level=0` | integration | control | `test_phpstan_with_neon_does_not_force_level_zero` |

### D19 — timeout + unavailable toolchain

Use existing `analyzers/budget.py` (inline cap) and `manifest.timeout_s` /
`run_plan` skip → `unavailable`. No new budget system.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| D19a | Each of the four declares `timeout_s > 0` | unit | happy | `test_four_cheap_flips_declare_timeout` |
| D19b | Resolved plan copies `manifest.timeout_s` | unit | happy | `test_flipped_tool_plan_carries_manifest_timeout` |
| D19c | Missing toolchain → `skip` / `unavailable` | integration | error | `test_flipped_tool_reports_unavailable_when_toolchain_absent` |
| D19d | Findings from the four still honor inline budget | unit | edge | `test_four_cheap_flips_findings_honor_inline_budget` |

### W2 default_enabled (xfail)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| W2a | Four manifests `default_enabled == "auto"` | unit | happy | `test_four_cheap_flips_default_enabled_auto` |
| W2b | `detect_enabled` includes each tool on its language markers | integration | happy | `test_four_cheap_flips_auto_enables_on_language_markers` |

## Already green vs RED

| Class | Expected at W1 close |
|-------|----------------------|
| Detect globs already in the manifests (`*.go`, `*.rs`, `Cargo.toml`, `*.rb`, `.rubocop.yml`, `*.php`, `phpstan.neon`) | **green** |
| Detect globs W1.1 names but manifests omit (`go.mod`, `Gemfile`, `composer.json`) | **RED** until W2 adds them |
| `default_enabled: auto` + auto `detect_enabled` | **xfail** until W2 |
| D11 with-config enablement | **xfail** until W2 (same auto marker) |
| D11 without-config | **green** now; must stay green after auto |
| D12 `--level=0` without neon | **xfail** until W2 |
| D12 neon present / neon detect globs | **green** |
| D15 SARIF fixtures / D19 timeout + unavailable | **green** |

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)
- No Batch X/Y/Z fixtures
