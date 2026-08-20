# Open issues sweep 2026-08-19e — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19e-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19e` @ `wave/open-issues-sweep-2026-08-19e`
Authoring waves: **W1** (Batch W RED — #338) · **W3** (Batch X RED — #337) · **W7** (Batch Y RED — #309-#327 leftovers) · **W18** (Batch Z RED — #328-#336)
Reconciliation: **W2.3** un-xfail after W2 (`533dfd4`); **W4 recon** un-xfail `tsc`/`bandit`/`jscpd`; **W5 recon** un-xfail `govulncheck`/`cargo-audit`/`cargo-deny`/`typos`; **W6.2 recon** un-xfail `knip`/`vulture` (all #337 new-manifest xfails gone); **W8 recon** un-xfail D16 no-config mypy + osv-scanner `uv.lock` (`c77469e` impl); **W9 recon** un-xfail D17 biome-over-eslint + biome/eslint `supports_fix` (`10dda8d` impl); **W10 recon** un-xfail brakeman auto+Rails + bundler-audit catalog (`b5165e9` impl); **W12 recon** un-xfail cppcheck auto (`ce31bee6` impl); **W13 recon** un-xfail detekt + swiftlint auto (`88b348ca` impl); **W14 recon** un-xfail pmd auto (`5174cedd` impl); **W15 recon** un-xfail sqlfluff + stylelint + htmlhint auto (`6847b055` impl); **W16 recon** un-xfail yamllint auto (`dfb2b97a` impl); **W17 recon** un-xfail checkmake + markdownlint + tflint + checkov auto (`a0b00e46` impl)

W7 pins leftover A-tier acceptances for #309-#327. Do **not** re-add tsc/bandit/jscpd/govulncheck/cargo-audit/cargo-deny/typos/knip/vulture (D10). Do **not** re-flip golangci-lint/clippy/rubocop/phpstan (D7). File: `tests/analyzers/test_a_tier_residuals.py` + `tests/analyzers/fixtures/batch-y/`. All cross-wave markers are `strict=False`.

W18 pins B-tier detect fixtures for #328-#336. Do **not** flip `default_enabled` (W19). File: `tests/analyzers/test_b_tier_flips.py` + `tests/analyzers/fixtures/batch-z/`. Do **not** lift F-tier (D9). `strict=False` on every `green after W19` marker.

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

File: `tests/analyzers/test_a_tier_residuals.py`. **0** remaining xfails after W17 recon (was 8). **0** XPASS. W11 has **0** xfails (phpcs/phpmd stay false). Batch Y A-tier tests are real passes (plus intentional skips if any).

| Wave | xfail count | Marker reason prefix |
|------|-------------|----------------------|
| **W8** | 0 | `green after W8:` D16 no-config mypy; osv-scanner `uv.lock` — **green** after W8 recon |
| **W9** | 0 | `green after W9:` D17 biome over eslint+scripts; biome/eslint `supports_fix` — **green** after W9 recon |
| **W10** | 0 | `green after W10:` brakeman auto+Rails; bundler-audit catalog — **green** after W10 recon |
| **W11** | 0 | phpcs/phpmd remain false (already green; phpstan is enough) |
| **W12** | 0 | `green after W12:` cppcheck auto (SAST path; not Semgrep `languages:`) — **green** after W12 recon |
| **W13** | 0 | `green after W13:` detekt + swiftlint auto — **green** after W13 recon |
| **W14** | 0 | `green after W14:` pmd auto — **green** after W14 recon |
| **W15** | 0 | `green after W15:` sqlfluff + stylelint + htmlhint auto — **green** after W15 recon |
| **W16** | 0 | `green after W16:` yamllint auto — **green** after W16 recon |
| **W17** | 0 | `green after W17:` checkmake + markdownlint + tflint + checkov auto — **green** after W17 recon |

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
| W15 | — | **green** after W15 recon: sqlfluff auto + `*.sql`; stylelint auto + `*.css`; htmlhint auto + `*.html`; HTML a11y gap: no axe/pa11y/html-validate catalog row (document, do not add) |
| W16 | — | **green** after W16 recon: yamllint auto + `*.yaml`; shellcheck auto; hadolint auto; do not add shfmt/dockle (D9 / catalog-rows-only) |
| W17 | — | **green** after W17 recon: checkmake auto + `Makefile`; markdownlint auto + `*.md`; tflint + checkov auto + `*.tf`; `exclusive_group` cleared on tflint/checkov so both enable; languagetool stays false |

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
| Y15 | sqlfluff/stylelint/htmlhint auto; a11y gap | unit | happy | `test_sqlfluff_*`, `test_html_a11y_catalog_gap_no_axe_or_pa11y` | **green** after W15 recon |
| Y16 | yamllint auto; shell/docker already on | unit | happy | `test_yamllint_*`, `test_shellcheck_already_auto` | **green** after W16 recon |
| Y17 | checkmake/markdownlint/tflint/checkov auto | integration | happy | `test_checkmake_*`, `test_tflint_*`, `test_checkov_*` | **green** after W17 recon |

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

## Acceptance (W15 recon)

- Removed 6 `green after W15:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W15 assertions are real passes: `test_sqlfluff_default_enabled_auto`, `test_sqlfluff_auto_enables_on_sql_fixture`, `test_stylelint_default_enabled_auto`, `test_stylelint_auto_enables_on_css_fixture`, `test_htmlhint_default_enabled_auto`, `test_htmlhint_auto_enables_on_html_fixture`
- W16–W17 xfails remain (`strict=False`); 0 XPASS for W15. W16 reminder: 2 xfails — yamllint `auto` (shellcheck/hadolint already auto; do not add shfmt/dockle)
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W16 recon)

- Removed 2 `green after W16:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W16 assertions are real passes: `test_yamllint_default_enabled_auto`, `test_yamllint_auto_enables_on_yaml_fixture`
- W17 xfails remain (`strict=False`); 0 XPASS for W16. W17 reminder: 8 xfails — checkmake / markdownlint / tflint / checkov `auto`. W7 note: tflint/checkov already detect `*.tf`; exclusive_group `iac-scanner` will collapse both unless W17 splits it (see W17 exact contracts below)
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

## Acceptance (W17 recon)

- Removed 8 `green after W17:` xfails from `tests/analyzers/test_a_tier_residuals.py`
- W17 assertions are real passes: `test_checkmake_default_enabled_auto`, `test_checkmake_auto_enables_on_makefile`, `test_markdownlint_default_enabled_auto`, `test_markdownlint_auto_enables_on_markdown_fixture`, `test_tflint_default_enabled_auto`, `test_tflint_auto_enables_on_terraform_fixture`, `test_checkov_default_enabled_auto`, `test_checkov_auto_enables_on_terraform_fixture`
- Batch Y A-tier tests: **0** remaining xfails, **0** XPASS (intentional skips if any). No YF yet
- `make lint` + `make typecheck` pass
- No product/source edits (`src/` untouched)

### W17 #325/#326/#327 — exact contracts for wave-plan-executor

W17 landed (`a0b00e46`); all 8 `green after W17:` markers removed. Do **not** add `lychee`. `languagetool` stays `false` (`test_languagetool_stays_opt_in`).

1. **checkmake (#325)** — `test_checkmake_default_enabled_auto`: `get_manifest("checkmake").default_enabled == "auto"`. `test_checkmake_auto_enables_on_makefile`: `"checkmake" in detect_enabled(repo=batch-y/make, changed_files=["Makefile"])`.
2. **markdownlint (#326)** — `test_markdownlint_default_enabled_auto`: `get_manifest("markdownlint").default_enabled == "auto"`. `test_markdownlint_auto_enables_on_markdown_fixture`: `"markdownlint" in detect_enabled(repo=batch-y/markdown, changed_files=["README.md"])`.
3. **tflint + checkov already detect `*.tf` (green; do not xfail)** — `test_tflint_and_checkov_already_detect_tf`: `filter_changed_files_for_manifest(tflint, ["main.tf"]) == ["main.tf"]` and same for checkov.
4. **tflint `auto` (#327)** — `test_tflint_default_enabled_auto`: `get_manifest("tflint").default_enabled == "auto"`. `test_tflint_auto_enables_on_terraform_fixture`: `"tflint" in detect_enabled(repo=batch-y/terraform, changed_files=["main.tf"])`. Docstring: both IaC tools must auto-enable; split `iac-scanner` if it collapses them.
5. **checkov `auto` (#327)** — `test_checkov_default_enabled_auto`: `get_manifest("checkov").default_enabled == "auto"`. `test_checkov_auto_enables_on_terraform_fixture`: `"checkov" in detect_enabled(repo=batch-y/terraform, changed_files=["main.tf"])`.

**`iac-scanner` trap (resolved in W17):** W17 cleared `exclusive_group` on tflint and checkov so both auto-enable on `*.tf`. Both membership asserts pass on the same `batch-y/terraform` + `["main.tf"]` call.

## Batch Z xfail schedule (W18 — RED until W19)

File: `tests/analyzers/test_b_tier_flips.py`. Fixtures: `tests/analyzers/fixtures/batch-z/`. All markers `strict=False`. Do **not** xfail detect globs that already match current YAML.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W19** | `test_b_tier_default_enabled_auto` (9 ids) | `green after W19: B-tier default_enabled auto (#328-#336)` | RED |
| **W19** | `test_b_tier_auto_enables_on_detect_markers` (9 ids) | same | RED |
| **W19** | `test_b_tier_w19_extra_detect_globs` | `green after W19: fortitude/psscriptanalyzer extra detect globs (#329/#331)` | RED |
| **W19** | `test_psscriptanalyzer_declares_supports_fix` | `green after W19: psscriptanalyzer supports_fix (#331)` | RED |
| **W19** | `test_ember_template_lint_declares_supports_fix` | `green after W19: ember-template-lint supports_fix (#335)` | RED |
| **W19** | `test_shopify_theme_check_auto_enables_on_theme_layout_without_yml` | `green after W19: shopify-theme-check theme layout markers (#333)` | RED |
| **W19** | `test_ember_template_lint_auto_enables_on_ember_source_package_json` | `green after W19: ember-template-lint ember-source package.json marker (#335)` | RED |
| **W19** | `test_smarty_lint_docs_note_tpl_ambiguity` | `green after W19: smarty-lint documents *.tpl ambiguity (#334)` | RED |
| **W19** | `test_prisma_lint_ships_conservative_fallback_ruleset` | `green after W19: prisma-lint conservative fallback ruleset (#336)` | RED |
| **W19** | `test_prisma_lint_without_rules_uses_conservative_fallback` | `green after W19: prisma-lint uses fallback when no repo rules (#336)` | RED |

### Already green (do not xfail)

| Contract | Test |
|----------|------|
| Current detect globs | `test_b_tier_language_marker_matches_detect_globs` |
| Unrelated `README.md` / empty changed files | `test_b_tier_markers_do_not_match_unrelated_paths`, `test_empty_changed_files_do_not_enable_b_tier` |
| D15 SARIF fixtures | `test_b_tier_has_catalog_check_parser_fixture` |
| D19 `timeout_s` + missing toolchain → `unavailable` + inline budget | `test_b_tier_declares_timeout`, `test_b_tier_reports_unavailable_when_toolchain_absent`, `test_b_tier_findings_honor_inline_budget` |
| D9 F-tier stays absent | `test_f_tier_languages_are_not_lifted` |
| Fixture trees on disk | `test_batch_z_detect_fixture_trees_exist` |
| Bare `*.liquid` is **not** a theme | `test_shopify_theme_check_does_not_auto_enable_on_bare_liquid` |
| Bare `*.hbs` is **not** Ember | `test_ember_template_lint_does_not_auto_enable_on_bare_hbs` |

Bare-liquid / bare-hbs stay green today because `default_enabled` is `false`. After the W19 `auto` flip they **must stay green** — that is the theme/ember gate. Do not remove `*.liquid` / `*.hbs` from `detect.files` without keeping `_auto_manifest_enabled` (or equivalent) so a real theme/Ember repo still fires on those paths.

## Batch Z contract matrix

| # | Contract | Layer | Scenario | Primary test | After W18 |
|---|----------|-------|----------|--------------|-----------|
| Z1 | Current detect globs | unit | happy | `test_b_tier_language_marker_matches_detect_globs` | **green** |
| Z2 | Nested / config globs already in YAML | unit | edge | same table (`src/hello.lua`, `policy/allow.rego`, `sections/header.liquid`, `prisma/schema.prisma`) | **green** |
| Z3 | Unrelated / empty changed files | unit | edge | `test_b_tier_markers_do_not_match_unrelated_paths` | **green** |
| Z4 | D15 parser fixture | unit | happy | `test_b_tier_has_catalog_check_parser_fixture` | **green** |
| Z5 | D19 timeout + unavailable + budget | unit/integration | error/edge | `test_b_tier_declares_timeout`, `test_b_tier_reports_unavailable_when_toolchain_absent`, `test_b_tier_findings_honor_inline_budget` | **green** |
| Z6 | D9 F-tier not added | unit | error | `test_f_tier_languages_are_not_lifted` | **green** |
| Z7 | `default_enabled == "auto"` | unit | happy | `test_b_tier_default_enabled_auto` | **xfail W19** |
| Z8 | `detect_enabled` on language/theme/ember/prisma fixtures | integration | happy | `test_b_tier_auto_enables_on_detect_markers` | **xfail W19** |
| Z9 | Fortitude `*.F90` / `*.f03` / `*.f` / `*.for`; PSSAanalyzer `*.psd1` | unit | happy | `test_b_tier_w19_extra_detect_globs` | **xfail W19** |
| Z10 | `psscriptanalyzer.supports_fix is True` | unit | happy | `test_psscriptanalyzer_declares_supports_fix` | **xfail W19** |
| Z11 | Theme layout without `.theme-check.yml` still auto-enables | integration | happy | `test_shopify_theme_check_auto_enables_on_theme_layout_without_yml` | **xfail W19** |
| Z12 | Bare `*.liquid` does not auto-enable | integration | edge | `test_shopify_theme_check_does_not_auto_enable_on_bare_liquid` | **green** |
| Z13 | Document `*.tpl` ambiguity in ANALYZERS.md notes | unit | happy | `test_smarty_lint_docs_note_tpl_ambiguity` | **xfail W19** |
| Z14 | Ember marker (`ember-cli-build.js`) auto-enables | integration | happy | `test_b_tier_auto_enables_on_detect_markers[ember-template-lint-…]` | **xfail W19** |
| Z15 | Ember marker (`ember-source` in `package.json`) auto-enables | integration | happy | `test_ember_template_lint_auto_enables_on_ember_source_package_json` | **xfail W19** |
| Z16 | Bare `*.hbs` does not auto-enable | integration | edge | `test_ember_template_lint_does_not_auto_enable_on_bare_hbs` | **green** |
| Z17 | `ember-template-lint.supports_fix is True` | unit | happy | `test_ember_template_lint_declares_supports_fix` | **xfail W19** |
| Z18 | Prisma conservative fallback ruleset file | unit | happy | `test_prisma_lint_ships_conservative_fallback_ruleset` | **xfail W19** |
| Z19 | No repo prisma-lint rules → still uses fallback (not inert skip) | integration | happy | `test_prisma_lint_without_rules_uses_conservative_fallback` | **xfail W19** |

### W19 #328-#336 — exact contracts for wave-plan-executor

Flip these nine existing manifests to `default_enabled: auto`. Do **not** add F-tier languages (D9). Honour D19 (existing `budget.py` / skip → `unavailable`). `make catalog-check` + CHANGELOG in the same commit. Do not touch 19c/19d paths (D6).

| Issue | id | Detect files W19 must satisfy | Extra |
|---|---|---|---|
| #328 | `luacheck` | already: `*.lua`, `.luacheckrc` | flip `auto` |
| #329 | `fortitude` | already: `*.f90`, `*.f95`, `.fortitude.toml`. **Add** `*.F90`, `*.f03`, `*.f`, `*.for` | flip `auto` |
| #330 | `regal` | already: `*.rego` | flip `auto` |
| #331 | `psscriptanalyzer` | already: `*.ps1`, `*.psm1`. **Add** `*.psd1` | `supports_fix: true` |
| #332 | `blinter` | already: `*.bat`, `*.cmd` | flip `auto` |
| #333 | `shopify-theme-check` | already: `*.liquid`, `.theme-check.yml` (keep globs). **Gate auto** on `.theme-check.yml` **or** on-disk `sections/` + `templates/` + `snippets/`. Bare `hello.liquid` must stay off | theme markers |
| #334 | `smarty-lint` | already: `*.tpl`, `.smarty-lint.json` | `docs/ANALYZERS.md` notes must mention `*.tpl` **ambiguity** (Go/Terraform templates). Generator lives in `catalog_docs.py` |
| #335 | `ember-template-lint` | already: `*.hbs`, `.template-lintrc.js` (keep globs). **Gate auto** on `ember-cli-build.js` **or** `ember-source` in `package.json`. Bare `hello.hbs` must stay off | `supports_fix: true` |
| #336 | `prisma-lint` | already: `*.prisma` (`schema.prisma`, `prisma/schema.prisma`) | conservative built-in fallback ruleset beside the catalog YAML (as `semgrep-default-rules.yml`); no-rules resolve must not skip as inert — argv/`config_note` includes fallback/default/`@catalog:` |

Detect fixture trees: `tests/analyzers/fixtures/batch-z/` (`lua`, `fortran`, `rego`, `powershell`, `batch`, `liquid-theme`, `liquid-theme-layout`, `liquid-bare`, `smarty`, `ember`, `ember-source`, `hbs-bare`, `prisma`).

## Acceptance (W18)

- Detect glob tests against current manifests are real passes (0 xfail on those)
- `default_enabled: auto` + `detect_enabled` + W19 extras are `strict=False` xfails tagged `green after W19`
- `make lint` + `make typecheck` pass; collection has 0 import errors
- No product/source edits (`src/` untouched)
- No `strict=True` on Batch Z markers
