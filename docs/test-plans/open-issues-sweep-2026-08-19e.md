# Open issues sweep 2026-08-19e — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19e-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19e` @ `wave/open-issues-sweep-2026-08-19e`
Authoring waves: **W1** (Batch W RED — #338) · **W3** (Batch X RED — #337) · **W7** (Batch Y RED — #309-#327 leftovers)
Reconciliation: **W2.3** un-xfail after W2 (`533dfd4`); **W4 recon** un-xfail `tsc`/`bandit`/`jscpd`; **W5 recon** un-xfail `govulncheck`/`cargo-audit`/`cargo-deny`/`typos`; **W6.2 recon** un-xfail `knip`/`vulture` (all #337 new-manifest xfails gone); **W8 recon** un-xfail D16 no-config mypy + osv-scanner `uv.lock` (`c77469e` impl); **W9 recon** un-xfail D17 biome-over-eslint + biome/eslint `supports_fix` (`10dda8d` impl); **W10 recon** un-xfail brakeman auto+Rails + bundler-audit catalog (`b5165e9` impl); **W12 recon** un-xfail cppcheck auto (`ce31bee6` impl); **W13 recon** un-xfail detekt + swiftlint auto (`88b348ca` impl); **W14 recon** un-xfail pmd auto (`5174cedd` impl)

W7 pins leftover A-tier acceptances for #309-#327. Do **not** re-add tsc/bandit/jscpd/govulncheck/cargo-audit/cargo-deny/typos/knip/vulture (D10). Do **not** re-flip golangci-lint/clippy/rubocop/phpstan (D7). File: `tests/analyzers/test_a_tier_residuals.py` + `tests/analyzers/fixtures/batch-y/`. All cross-wave markers are `strict=False`.

W1 pinned detect + catalog-check fixtures for `golangci-lint`, `clippy`, `rubocop`,
and `phpstan` (D7). W2 greened `default_enabled: auto` and applied D11 / D12 / D19.
W2.3 removed the W1.1 `green after W2` xfail markers.

W3 pins **#337 new manifests** (D10) minus C# / F-tier second list (D9). Fixture
skeletons live under `tests/analyzers/fixtures/batch-x/` plus
`tests/analyzers/fixtures/sarif/<id>-minimal.sarif.json`. Catalog YAML is **W4–W6**
— do not add it in W3.

Batch X (#337) has **0** remaining xfails. Do not use `strict=True`
(`xfail_strict = true` in `pyproject.toml`) on any later Batch Y/Z RED markers.

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

### Batch X (W3 — RED until W6; W4 + W5 + W6 greened)

File: `tests/analyzers/test_new_manifests_337.py`. No `@pytest.mark.xfail` remains
for #337 new manifests after W6.2.

| Wave | Ids | Marker reason prefix | Status |
|------|-----|----------------------|--------|
| **W4** | `tsc`, `bandit`, `jscpd` | `green after W4: <id> catalog manifest (#337)` | **green** after W4 recon |
| **W4** | `tsc` command/scope | `green after W4: tsc --noEmit whole-program catalog (#337)` | **green** after W4 recon |
| **W4** | `bandit` version | `green after W4: bandit reuses make security pin (#337)` | **green** after W4 recon |
| **W4** | `jscpd` D14 | `green after W4: jscpd scope repo + diff-line attribution (D14)` | **green** after W4 recon |
| **W4** | `tsc` diff-filter | `green after W4: tsc whole-program + diff-filter (#337)` | **green** after W4 recon |
| **W5** | `govulncheck`, `cargo-audit`, `cargo-deny`, `typos` | `green after W5: <id> catalog manifest (#337)` | **green** after W5 recon |
| **W5** | cargo pair | `green after W5: cargo-audit vs cargo-deny are distinct ids (#337)` | **green** after W5 recon |
| **W6** | `knip`, `vulture` | `green after W6: <id> catalog manifest (#337)` | **green** after W6.2 recon |

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

| # | Contract | Layer | Scenario | Primary test | After W6.2 recon |
|---|----------|-------|----------|--------------|------------------|
| X1 | Catalog YAML exists / `get_manifest` importable | unit | happy | `test_new_manifest_catalog_yaml_exists`, `test_new_manifest_is_importable` | **green** |
| X2 | `default_enabled == "auto"` | unit | happy | `test_new_manifest_default_enabled_auto` | **green** |
| X3 | Category per #337 | unit | happy | `test_new_manifest_category` | **green** |
| X4 | Detect globs (see table below) | unit | happy | `test_new_manifest_detect_globs` | **green** |
| X5 | `detect_enabled` on fixture markers | integration | happy | `test_new_manifest_auto_enables_on_detect_markers` | **green** |
| X6 | Empty changed files do not enable new ids | unit | edge | `test_empty_changed_files_do_not_enable_new_manifests` | **green** |
| X7 | README.md does not enable (except typos/jscpd) | unit | edge | `test_unrelated_readme_does_not_match_before_manifest` | **green** (2 skips: typos/jscpd) |
| X8 | D9: no C# / Roslyn / second-tier ids | unit | error | `test_deferred_tools_are_not_in_catalog` | **green** |
| X9 | Parser skeleton under `sarif/` or `native/` | unit | happy | `test_batch_x_catalog_check_parser_skeleton_exists` | **green** |
| X10 | Detect fixture tree per id | unit | happy | `test_batch_x_detect_fixture_skeleton_exists` | **green** |
| X11 | D15 `manifest_has_fixture` after YAML lands | unit | happy | `test_new_manifest_has_catalog_check_parser_fixture` | **green** |
| X12 | `timeout_s > 0` | unit | happy | `test_new_manifest_declares_timeout` | **green** |
| X13 | Missing toolchain → skip / `unavailable` (D19) | integration | error | `test_new_manifest_reports_unavailable_when_toolchain_absent` | **green** |
| X14 | Findings honor inline budget (D19) | unit | edge | `test_new_manifest_findings_honor_inline_budget` (all nine ids, 27 findings) | **green** |
| X15 | `tsc --noEmit`; `scope: repo`; category `lint` | unit | happy | `test_tsc_command_is_no_emit_whole_program` | **green** |
| X16 | `tsc` whole-program + diff-filter | unit | edge | `test_tsc_diff_filter_keeps_only_changed_lines` | **green** |
| X17 | `bandit` version == `bandit[toml]` pin in `pyproject.toml` (`1.9.4`); category `security` | unit | happy | `test_bandit_version_reuses_make_security_pin`, `test_make_security_bandit_pin_is_present` | **green** |
| X18 | D14: `jscpd` `scope: repo` | unit | happy | `test_jscpd_scope_is_repo` | **green** |
| X19 | D14: drop pre-existing clones off the diff | unit | edge | `test_jscpd_drops_preexisting_clones_off_the_diff` | **green** |
| X20 | `cargo-audit` (`vuln`) ≠ `cargo-deny` (`license`) | unit | happy | `test_cargo_audit_and_deny_are_distinct_catalog_ids` | **green** |

Detect globs W4 must satisfy (`tsc` / `bandit` / `jscpd`):

| id | `detect.files` must match | `category` | `default_enabled` | extra |
|----|---------------------------|------------|-------------------|-------|
| `tsc` | `tsconfig.json`, `*.ts` (`src/index.ts`), `*.tsx` (`src/index.tsx`) | `lint` | `auto` | `command` contains `--noEmit`; `scope: repo`; diff-filter results |
| `bandit` | `*.py` (`hello.py`) | `security` | `auto` | `command[0] == "bandit"`; `version` == pyproject `bandit[toml]==1.9.4` |
| `jscpd` | `src/clone-a.js`, `src/index.ts`, `hello.py` | `quality` | `auto` | `scope: repo`; findings attributed to **diff lines** only (D14) |

Detect globs W5 / W6 (all greened after W6.2):

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

| Class | Status after W6.2 recon |
|-------|-------------------------|
| Detect globs (`*.go`, `*.rs`, `Cargo.toml`, `*.rb`, `.rubocop.yml`, `*.php`, `phpstan.neon`, `go.mod`, `Gemfile`, `composer.json`) | **green** (Batch W) |
| `default_enabled: auto` + auto `detect_enabled` (four cheap flips) | **green** |
| D11 / D12 / D15 SARIF / D19 for the four | **green** |
| Batch X fixture skeletons + SARIF skeletons | **green** (W3) |
| D9 deferred ids absent | **green** (W3; Roslyn not added) |
| Empty changed files do not enable #337 ids | **green** (W3; stays green after YAML) |
| #337 `tsc` / `bandit` / `jscpd` catalog YAML / import / auto / category / detect | **green** after W4 recon |
| D14 jscpd `scope: repo` + diff-line filter | **green** after W4 recon |
| `tsc --noEmit` + `scope: repo` | **green** after W4 recon |
| `bandit` version == make-security pin | **green** after W4 recon |
| #337 `govulncheck` / `cargo-audit` / `cargo-deny` / `typos` catalog YAML | **green** after W5 recon |
| `cargo-audit` (`vuln`) ≠ `cargo-deny` (`license`) | **green** after W5 recon |
| #337 `knip` / `vulture` catalog YAML | **green** after W6.2 recon |
| #337 new-manifest xfails | **none** (0 xfail / 0 XPASS) |

## Acceptance (W6.2 recon)

- W6 `knip` / `vulture` assertions are real passes (no `green after W6` xfail; 0 XPASS)
- Batch X `#337` file has **0** remaining xfails (intentional skips only: typos/jscpd README)
- D9: Roslyn / C# / F-tier second-tier ids still absent
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Batch Y xfail schedule (W7 — RED until W8-W17)

File: `tests/analyzers/test_a_tier_residuals.py`. **16** remaining `strict=False` xfails after W14 recon (was 18). **0** XPASS for W14. W11 has **0** xfails (phpcs/phpmd stay false).

| Wave | xfail count | Marker reason prefix |
|------|-------------|----------------------|
| **W8** | 0 | `green after W8:` D16 no-config mypy; osv-scanner `uv.lock` — **green** after W8 recon |
| **W9** | 0 | `green after W9:` D17 biome over eslint+scripts; biome/eslint `supports_fix` — **green** after W9 recon |
| **W10** | 0 | `green after W10:` brakeman auto+Rails; bundler-audit catalog — **green** after W10 recon |
| **W11** | 0 | phpcs/phpmd remain false (already green; phpstan is enough) |
| **W12** | 0 | `green after W12:` cppcheck auto (SAST path; not Semgrep `languages:`) — **green** after W12 recon |
| **W13** | 0 | `green after W13:` detekt + swiftlint auto — **green** after W13 recon |
| **W14** | 0 | `green after W14:` pmd auto — **green** after W14 recon |
| **W15** | 6 | `green after W15:` sqlfluff + stylelint + htmlhint auto |
| **W16** | 2 | `green after W16:` yamllint auto |
| **W17** | 8 | `green after W17:` checkmake + markdownlint + tflint + checkov auto |

### W8 #309 Python — exact contracts for wave-plan-executor

1. **D16 exclusive_group** already exists (`python-typecheck` on mypy/pyright/basedpyright). Do not invent a second group. **green**.
2. **Config-file winner (already green):** `mypy.ini` → mypy; `pyrightconfig.json` → pyright *or* basedpyright (not mypy); `[tool.basedpyright]` → basedpyright. Never all three.
3. **No type-checker config → mypy still wins** (`test_no_typechecker_config_defaults_to_mypy`). **green** after W8 recon.
4. **flake8 / pylint** stay catalog rows, `default_enabled: false`, `exclusive_group: python-lint`. Document as legacy opt-in in `docs/ANALYZERS.md`. Do not delete. **green** (docs prose is W8.1 CHANGELOG/docs).
5. **bandit / vulture** already `auto` from X. Do not re-add. **green**.
6. **osv-scanner** already matches `requirements.txt`. **green**.
7. **osv-scanner must match `uv.lock`** (and auto-enable on that fixture). Do **not** add `pip-audit`. **green** after W8 recon.

### W9 #310 JS/TS

- `eslint` / `biome` / `oxlint` already share `exclusive_group: js-lint`. Config-only fixtures already pick biome > eslint > oxlint. **green**.
- **D17:** `biome.json` beats eslint even when `package.json` has eslint scripts/deps. **green** after W9 recon.
- `supports_fix: true` on biome and eslint. **green** after W9 recon.
- tsc / knip already auto from X. **green**.

### W10 #311/#313/#314

- Go: golangci-lint + govulncheck already auto; detect `go.mod` / `*.go`. **green**. Do not re-flip.
- Rust: clippy + cargo-audit + cargo-deny already auto. **green**. Do not re-flip clippy.
- Ruby: rubocop already auto. **green**.
- **green after W10 recon:** brakeman `default_enabled: auto` and auto-enable on Rails markers (`config/application.rb` / `gem "rails"`). Plain Ruby must stay off (already green).
- **green after W10 recon:** `bundler-audit` catalog YAML (`auto`, detect `Gemfile.lock`, SARIF fixture at `tests/analyzers/fixtures/sarif/bundler-audit-minimal.sarif.json`). osv-scanner already covers `Gemfile.lock` (**green**).

### W11 #316 PHP (decision pinned)

**phpcs and phpmd remain `default_enabled: false`** even when `phpcs.xml` is present. Detection is not treated as tight enough to join auto. **phpstan is enough** default PHP signal (already auto). No W11 xfails.

### W12 #315 C/C++ (SAST choice pinned)

**Default SAST path is flip `cppcheck` to `auto`**, not a Semgrep `languages:` add. cppcheck needs no compile database; clang-tidy stays `false` (opt-in). Semgrep is **not** required to list `c`/`cpp`. Do not add `flawfinder`. **green** after W12 recon: cppcheck auto + detect_enabled on `hello.c` / `hello.cpp`.

### W13-W17 leftovers

| Wave | RED | Already green (do not xfail) |
|------|-----|------------------------------|
| W13 | — | **green** after W13 recon: detekt auto + `*.kt`; swiftlint auto + `*.swift` |
| W14 | — | **green** after W14 recon: pmd auto + `*.java`; **D13** infer stays `false`; Java SAST via Semgrep `languages: java` |
| W15 | sqlfluff / stylelint / htmlhint auto | HTML a11y gap: no axe/pa11y/html-validate catalog row (document, do not add) |
| W16 | yamllint auto | shellcheck auto; hadolint auto; do not add shfmt/dockle (D9 / catalog-rows-only) |
| W17 | checkmake / markdownlint / tflint / checkov auto | languagetool stays false; tflint+checkov already detect `*.tf`. `iac-scanner` exclusive_group currently collapses both; W17 must split it or both-enable (finding-level dedup) so both auto tests pass |

## Batch Y contract matrix

| # | Contract | Layer | Scenario | Primary test | After W7 |
|---|----------|-------|----------|--------------|----------|
| Y8a | D16 no-config → mypy | integration | happy | `test_no_typechecker_config_defaults_to_mypy` | **green** after W8 recon |
| Y8b | osv-scanner `uv.lock` | unit | happy | `test_osv_scanner_covers_uv_lock` | **green** after W8 recon |
| Y8c | type-checker exclusive_group + config winners | integration | happy | `test_python_type_checkers_share_exclusive_group`, `test_mypy_ini_selects_mypy_not_pyright` | **green** |
| Y8d | flake8/pylint legacy opt-in | unit | happy | `test_flake8_pylint_remain_legacy_opt_in` | **green** |
| Y9a | D17 biome beats eslint+scripts | integration | happy | `test_biome_json_beats_eslint_even_with_eslint_script_signals` | **green** after W9 recon |
| Y9b | biome/eslint `supports_fix` | unit | happy | `test_biome_and_eslint_declare_supports_fix` | **green** after W9 recon |
| Y9c | js-lint exclusive_group config-only order | integration | happy | `test_biome_config_wins_js_lint_group` | **green** |
| Y10a | brakeman auto + Rails gate | integration | happy/edge | `test_brakeman_default_enabled_auto`, `test_brakeman_auto_enables_on_rails_markers`, `test_brakeman_does_not_auto_enable_on_plain_ruby` | **green** after W10 recon |
| Y10b | bundler-audit new manifest | unit | happy | `test_bundler_audit_*` | **green** after W10 recon |
| Y11 | phpcs/phpmd stay false; phpstan signal | integration | happy | `test_phpcs_remains_false_even_with_phpcs_xml`, `test_phpmd_remains_false`, `test_phpstan_is_enough_default_php_signal` | **green** |
| Y12 | cppcheck auto; clang-tidy opt-in | integration | happy | `test_cppcheck_default_enabled_auto`, `test_clang_tidy_stays_opt_in` | **green** after W12 recon |
| Y13 | detekt + swiftlint auto | integration | happy | `test_detekt_*`, `test_swiftlint_*` | **green** after W13 recon |
| Y14 | pmd auto; infer false (D13) | unit | happy | `test_pmd_default_enabled_auto`, `test_infer_stays_false` | **green** after W14 recon |
| Y15 | sqlfluff/stylelint/htmlhint auto; a11y gap | unit | happy | `test_sqlfluff_*`, `test_html_a11y_catalog_gap_no_axe_or_pa11y` | xfail / **green** |
| Y16 | yamllint auto; shell/docker already on | unit | happy | `test_yamllint_*`, `test_shellcheck_already_auto` | xfail / **green** |
| Y17 | checkmake/markdownlint/tflint/checkov auto | integration | happy | `test_checkmake_*`, `test_tflint_*`, `test_checkov_*` | xfail W17 |

Batch Y fixture trees: `tests/analyzers/fixtures/batch-y/` (`python-noconfig`, `python-mypy`, `python-pyright`, `python-basedpyright`, `python-uv`, `js-biome`, `js-eslint`, `js-oxlint`, `js-biome-over-eslint`, `rails`, `ruby-plain`, `bundler-audit`, `cpp`, `kotlin`, `swift`, `java`, `sql`, `css`, `html`, `yaml`, `make`, `markdown`, `terraform`, `php-phpcs`, `php-plain`).

## Acceptance (W7)

- 37 xfails, 0 XPASS, 0 collection errors
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)
- No `strict=True` on Batch Y markers

## Acceptance (W8 recon)

- Removed 3 `green after W8:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W8 assertions are real passes: `test_no_typechecker_config_defaults_to_mypy`, `test_osv_scanner_covers_uv_lock`, `test_osv_scanner_auto_enables_on_uv_lock_fixture`
- W9–W17 xfails remain (`strict=False`); 0 XPASS for W8
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W9 recon)

- Removed 3 `green after W9:` xfails from `tests/analyzers/test_a_tier_residuals.py` (1 biome-over-eslint + 2 parametrized biome/eslint `supports_fix`)
- W9 assertions are real passes: `test_biome_json_beats_eslint_even_with_eslint_script_signals`, `test_biome_and_eslint_declare_supports_fix` (`biome`, `eslint`)
- W10–W17 xfails remain (`strict=False`); 0 XPASS for W9
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W10 recon)

- Removed 7 `green after W10:` xfails from `tests/analyzers/test_a_tier_residuals.py` (2 brakeman auto+Rails + 5 bundler-audit catalog)
- W10 assertions are real passes: `test_brakeman_default_enabled_auto`, `test_brakeman_auto_enables_on_rails_markers`, `test_bundler_audit_catalog_yaml_exists`, `test_bundler_audit_is_importable_and_auto`, `test_bundler_audit_detects_gemfile_lock`, `test_bundler_audit_auto_enables_on_lockfile`, `test_bundler_audit_has_catalog_check_parser_fixture`
- W11 has 0 xfails (phpcs/phpmd stay false; phpstan is enough). W12–W17 xfails remain (`strict=False`); 0 XPASS for W10
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W12 recon)

- Removed 2 `green after W12:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W12 assertions are real passes: `test_cppcheck_default_enabled_auto`, `test_cppcheck_auto_enables_on_cpp_fixture`
- W13–W17 xfails remain (`strict=False`); 0 XPASS for W12. W13 reminder: 4 xfails — detekt + swiftlint `auto`
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W13 recon)

- Removed 4 `green after W13:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W13 assertions are real passes: `test_detekt_default_enabled_auto`, `test_detekt_auto_enables_on_kotlin_fixture`, `test_swiftlint_default_enabled_auto`, `test_swiftlint_auto_enables_on_swift_fixture`
- W14–W17 xfails remain (`strict=False`); 0 XPASS for W13. W14 reminder: 2 xfails — pmd `auto`; infer stays false (D13)
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W14 recon)

- Removed 2 `green after W14:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W14 assertions are real passes: `test_pmd_default_enabled_auto`, `test_pmd_auto_enables_on_java_fixture`
- W15–W17 xfails remain (`strict=False`); 0 XPASS for W14. W15 reminder: 6 xfails — sqlfluff / stylelint / htmlhint `auto`
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)
