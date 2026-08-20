# Open issues sweep 2026-08-19e — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19e-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19e` @ `wave/open-issues-sweep-2026-08-19e`
Authoring waves: **W1** (Batch W RED — #338) · **W3** (Batch X RED — #337)
Reconciliation: **W2.3** un-xfail after W2 (`533dfd4`); **W4 recon** un-xfail `tsc`/`bandit`/`jscpd`; W5–W6 un-xfail remaining Batch X after each impl wave

W1 pinned detect + catalog-check fixtures for `golangci-lint`, `clippy`, `rubocop`,
and `phpstan` (D7). W2 greened `default_enabled: auto` and applied D11 / D12 / D19.
W2.3 removed the W1.1 `green after W2` xfail markers.

W3 pins **#337 new manifests** (D10) minus C# / F-tier second list (D9). Fixture
skeletons live under `tests/analyzers/fixtures/batch-x/` plus
`tests/analyzers/fixtures/sarif/<id>-minimal.sarif.json`. Catalog YAML is **W4–W6**
— do not add it in W3.

All remaining cross-wave xfails use `strict=False`.
Do not use `strict=True` (`xfail_strict = true` in `pyproject.toml`).

## xfail schedule

### Batch W (historical — green after W2.3)

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_four_cheap_flips_default_enabled_auto` | `green after W2: four cheap flips default_enabled auto` | **green** after W2.3 |
| **W2** | `test_four_cheap_flips_auto_enables_on_language_markers` | `green after W2: four cheap flips default_enabled auto` | **green** after W2.3 |
| **W2** | `test_rubocop_auto_fires_when_config_is_present` | `green after W2: four cheap flips default_enabled auto` | **green** after W2.3 |
| **W2** | `test_rubocop_auto_fires_when_gemfile_declares_rubocop` | `green after W2: four cheap flips default_enabled auto` | **green** after W2.3 |
| **W2** | `test_phpstan_without_neon_runs_at_level_zero` | `green after W2: phpstan --level=0 without neon (D12)` | **green** after W2.3 |

No W2-scope xfails remain in `tests/analyzers/test_four_cheap_flips.py`.

### Batch X (W3 — RED until W5 / W6; W4 greened)

File: `tests/analyzers/test_new_manifests_337.py`. Parametrized catalog/import/detect/auto
tests for remaining ids carry `@pytest.mark.xfail(..., strict=False)` tagged `green after W5|W6`.

| Wave | Ids | Marker reason prefix | Status |
|------|-----|----------------------|--------|
| **W4** | `tsc`, `bandit`, `jscpd` | `green after W4: <id> catalog manifest (#337)` | **green** after W4 recon |
| **W4** | `tsc` command/scope | `green after W4: tsc --noEmit whole-program catalog (#337)` | **green** after W4 recon |
| **W4** | `bandit` version | `green after W4: bandit reuses make security pin (#337)` | **green** after W4 recon |
| **W4** | `jscpd` D14 | `green after W4: jscpd scope repo + diff-line attribution (D14)` | **green** after W4 recon |
| **W4** | `tsc` diff-filter | `green after W4: tsc whole-program + diff-filter (#337)` | **green** after W4 recon |
| **W5** | `govulncheck`, `cargo-audit`, `cargo-deny`, `typos` | `green after W5: <id> catalog manifest (#337)` | **xfail** |
| **W5** | cargo pair | `green after W5: cargo-audit vs cargo-deny are distinct ids (#337)` | **xfail** |
| **W6** | `knip`, `vulture` | `green after W6: <id> catalog manifest (#337)` | **xfail** |

`#337` §6 names **both** `cargo-audit` (category `vuln`) and `cargo-deny`
(category `license`). W3 pins both ids. Do not collapse them.

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

### D15 — catalog-check-shaped parser fixtures (Batch W)

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
| D11a | `.rubocop.yml` / `.yaml` / `.yml.dist` → enabled | integration | happy | `test_rubocop_auto_fires_when_config_is_present` |
| D11b | `Gemfile` declaring `gem "rubocop"` → enabled | integration | happy | `test_rubocop_auto_fires_when_gemfile_declares_rubocop` |
| D11c | `*.rb` + Gemfile with no config → not enabled | integration | error | `test_rubocop_without_config_is_not_enabled` |
| D11d | Adapter must not emit default-cop findings without config | functional | error | `test_rubocop_without_config_skips_unavailable_not_a_cop_dump` (skip/`unavailable`, not a fail) |
| D11e | Changing `.rubocop.yml` matches detect globs | unit | happy | `test_rubocop_detect_matches_shipped_config_glob` |

D11c/D11d stay green after the W2 auto flip because D11 config detection landed.

### D12 — `phpstan` neon vs `--level=0`

If `phpstan.neon` / `phpstan.neon.dist` exists, use it. Else run with `--level=0`.
Do not invent a mergeCraft neon. ANALYZERS.md note is W2.2 (`make catalog-check`).

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| D12a | `phpstan.neon` / `.dist` match detect globs | unit | happy | `test_phpstan_neon_globs_match_before_flip` |
| D12b | No neon → argv includes `--level=0` | integration | happy | `test_phpstan_without_neon_runs_at_level_zero` |
| D12c | Neon present → do not force `--level=0` | integration | control | `test_phpstan_with_neon_does_not_force_level_zero` |

### D19 — timeout + unavailable toolchain (Batch W)

Use existing `analyzers/budget.py` (inline cap) and `manifest.timeout_s` /
`run_plan` skip → `unavailable`. No new budget system.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| D19a | Each of the four declares `timeout_s > 0` | unit | happy | `test_four_cheap_flips_declare_timeout` |
| D19b | Resolved plan copies `manifest.timeout_s` | unit | happy | `test_flipped_tool_plan_carries_manifest_timeout` |
| D19c | Missing toolchain → `skip` / `unavailable` | integration | error | `test_flipped_tool_reports_unavailable_when_toolchain_absent` |
| D19d | Findings from the four still honor inline budget | unit | edge | `test_four_cheap_flips_findings_honor_inline_budget` |

### W2 default_enabled (green after W2.3)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| W2a | Four manifests `default_enabled == "auto"` | unit | happy | `test_four_cheap_flips_default_enabled_auto` |
| W2b | `detect_enabled` includes each tool on its language markers | integration | happy | `test_four_cheap_flips_auto_enables_on_language_markers` |

### W3.1 — #337 new manifests (D9 / D10 / D14 / D15 / D19)

Primary file: `tests/analyzers/test_new_manifests_337.py`.

| # | Contract | Layer | Scenario | Primary test | After W4 recon |
|---|----------|-------|----------|--------------|----------------|
| X1 | Catalog YAML exists / `get_manifest` importable | unit | happy | `test_new_manifest_catalog_yaml_exists`, `test_new_manifest_is_importable` | **green** W4 ids; **xfail** W5–W6 |
| X2 | `default_enabled == "auto"` | unit | happy | `test_new_manifest_default_enabled_auto` | **green** W4 ids; **xfail** W5–W6 |
| X3 | Category per #337 | unit | happy | `test_new_manifest_category` | **green** W4 ids; **xfail** W5–W6 |
| X4 | Detect globs (see table below) | unit | happy | `test_new_manifest_detect_globs` | **green** W4 ids; **xfail** W5–W6 |
| X5 | `detect_enabled` on fixture markers | integration | happy | `test_new_manifest_auto_enables_on_detect_markers` | **green** W4 ids; **xfail** W5–W6 |
| X6 | Empty changed files do not enable new ids | unit | edge | `test_empty_changed_files_do_not_enable_new_manifests` | **green** |
| X7 | README.md does not enable (except typos/jscpd) | unit | edge | `test_unrelated_readme_does_not_match_before_manifest` | **green** |
| X8 | D9: no C# / Roslyn / second-tier ids | unit | error | `test_deferred_tools_are_not_in_catalog` | **green** |
| X9 | Parser skeleton under `sarif/` or `native/` | unit | happy | `test_batch_x_catalog_check_parser_skeleton_exists` | **green** |
| X10 | Detect fixture tree per id | unit | happy | `test_batch_x_detect_fixture_skeleton_exists` | **green** |
| X11 | D15 `manifest_has_fixture` after YAML lands | unit | happy | `test_new_manifest_has_catalog_check_parser_fixture` | **green** W4 ids; **xfail** W5–W6 |
| X12 | `timeout_s > 0` | unit | happy | `test_new_manifest_declares_timeout` | **green** W4 ids; **xfail** W5–W6 |
| X13 | Missing toolchain → skip / `unavailable` (D19) | integration | error | `test_new_manifest_reports_unavailable_when_toolchain_absent` | **green** W4 ids; **xfail** W5–W6 |
| X14 | Findings honor inline budget (D19) | unit | edge | `test_new_manifest_findings_honor_inline_budget` (all nine ids, 27 findings) | **green** |
| X15 | `tsc --noEmit`; `scope: repo`; category `lint` | unit | happy | `test_tsc_command_is_no_emit_whole_program` | **green** |
| X16 | `tsc` whole-program + diff-filter | unit | edge | `test_tsc_diff_filter_keeps_only_changed_lines` | **green** |
| X17 | `bandit` version == `bandit[toml]` pin in `pyproject.toml` (`1.9.4`); category `security` | unit | happy | `test_bandit_version_reuses_make_security_pin`, `test_make_security_bandit_pin_is_present` | **green** |
| X18 | D14: `jscpd` `scope: repo` | unit | happy | `test_jscpd_scope_is_repo` | **green** |
| X19 | D14: drop pre-existing clones off the diff | unit | edge | `test_jscpd_drops_preexisting_clones_off_the_diff` | **green** |
| X20 | `cargo-audit` (`vuln`) ≠ `cargo-deny` (`license`) | unit | happy | `test_cargo_audit_and_deny_are_distinct_catalog_ids` | **xfail** W5 |

Detect globs W4 must satisfy (`tsc` / `bandit` / `jscpd`):

| id | `detect.files` must match | `category` | `default_enabled` | extra |
|----|---------------------------|------------|-------------------|-------|
| `tsc` | `tsconfig.json`, `*.ts` (`src/index.ts`), `*.tsx` (`src/index.tsx`) | `lint` | `auto` | `command` contains `--noEmit`; `scope: repo`; diff-filter results |
| `bandit` | `*.py` (`hello.py`) | `security` | `auto` | `command[0] == "bandit"`; `version` == pyproject `bandit[toml]==1.9.4` |
| `jscpd` | `src/clone-a.js`, `src/index.ts`, `hello.py` | `quality` | `auto` | `scope: repo`; findings attributed to **diff lines** only (D14) |

Detect globs W5 / W6 (not W4):

| id | Wave | must match | category |
|----|------|------------|----------|
| `govulncheck` | W5 | `go.mod`, `*.go` | `vuln` |
| `cargo-audit` | W5 | `Cargo.toml`, `Cargo.lock` | `vuln` |
| `cargo-deny` | W5 | `Cargo.toml`, `Cargo.lock`, `deny.toml` | `license` |
| `typos` | W5 | `hello.py`, `README.md` | `lint` |
| `knip` | W6 | `package.json`, `src/index.ts`, `src/index.js` | `quality` |
| `vulture` | W6 | `*.py` | `quality` |

Batch X fixture trees:

- `tests/analyzers/fixtures/batch-x/tsc/` — `tsconfig.json`, `src/index.ts`
- `tests/analyzers/fixtures/batch-x/bandit/` — `hello.py`
- `tests/analyzers/fixtures/batch-x/jscpd/` — `src/clone-a.js`, `src/clone-b.js` (identical clones)
- `tests/analyzers/fixtures/batch-x/govulncheck/` — `go.mod`, `hello.go`
- `tests/analyzers/fixtures/batch-x/cargo-audit/` — `Cargo.toml`, `Cargo.lock`
- `tests/analyzers/fixtures/batch-x/cargo-deny/` — `Cargo.toml`, `Cargo.lock`, `deny.toml`
- `tests/analyzers/fixtures/batch-x/typos/` — `hello.py`, `README.md`
- `tests/analyzers/fixtures/batch-x/knip/` — `package.json`, `src/index.ts`
- `tests/analyzers/fixtures/batch-x/vulture/` — `hello.py`

Parser skeletons: `tests/analyzers/fixtures/sarif/<id>-minimal.sarif.json` for each of the nine ids.

Deferred (must **not** appear — D9 / #337 second tier): `roslyn`, `roslyn-analyzers`,
`csharp`, `c-sharp`, `dotnet-format`, `dotnet_format`, `credo`, `dart-analyze`,
`dart_analyze`, `scalafix`, `shfmt`, `nbqa`, `lizard`, `atlas`.

## Already green vs RED

| Class | Status after W4 recon |
|-------|------------------------|
| Detect globs (`*.go`, `*.rs`, `Cargo.toml`, `*.rb`, `.rubocop.yml`, `*.php`, `phpstan.neon`, `go.mod`, `Gemfile`, `composer.json`) | **green** (Batch W) |
| `default_enabled: auto` + auto `detect_enabled` (four cheap flips) | **green** |
| D11 / D12 / D15 SARIF / D19 for the four | **green** |
| Batch X fixture skeletons + SARIF skeletons | **green** (W3) |
| D9 deferred ids absent | **green** (W3) |
| Empty changed files do not enable #337 ids | **green** (W3; stays green after YAML) |
| #337 `tsc` / `bandit` / `jscpd` catalog YAML / import / auto / category / detect | **green** after W4 recon |
| D14 jscpd `scope: repo` + diff-line filter | **green** after W4 recon |
| `tsc --noEmit` + `scope: repo` | **green** after W4 recon |
| `bandit` version == make-security pin | **green** after W4 recon |
| #337 `govulncheck` / `cargo-audit` / `cargo-deny` / `typos` catalog YAML | **xfail** until W5 |
| #337 `knip` / `vulture` catalog YAML | **xfail** until W6 |

## Acceptance (W4 recon)

- W4 `tsc` / `bandit` / `jscpd` assertions are real passes (no `green after W4` xfail; 0 XPASS)
- Remaining `strict=False` xfails tagged `green after W5` / `W6` only
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)
