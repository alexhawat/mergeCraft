# Test plan — open-issues-sweep-2026-08-24-a (AA #458 + AB #467)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-a-analyzers-ci-wave-plan.md`
Worktree: `/Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a`
Branch: `wave/open-issues-sweep-2026-08-24-a`
Issues: [#458](https://github.com/alexhawat/mergeCraft/issues/458), [#467](https://github.com/alexhawat/mergeCraft/issues/467)

Authoring: **AA GREEN** (D2 landed). **AB RED** (this update). Implementation: AB impl (D3). AC–AH not authored here.

## xfail schedule

None. AB contracts are the next impl wave; tests are **plain FAIL** until D3 lands. Do not `xfail` (would hide RED).

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AA458a | `validate_manifest(..., check_provenance=True)` rejects sha256 of 64 zero hex digits | unit | error — placeholder pin | `tests/analyzers/test_placeholder_provenance_458.py::test_validate_manifest_rejects_all_zero_sha256_pin` |
| AA458b | Empty `provenance: {}` and a real (non-zero) pin still validate | unit | happy | `test_validate_manifest_accepts_empty_provenance_and_real_pin` |
| AA458c | `validate_manifest_ship_gate` (`make catalog-check` path) rejects an all-zero pin when fixture + doc row exist | functional | error — catalog-check | `test_catalog_ship_gate_rejects_all_zero_sha256` |
| AA458d | Shipped `checkov` / `yamllint` YAML is `provenance: {}` like `semgrep` | unit | happy — catalog pins | `test_checkov_and_yamllint_ship_empty_provenance_like_semgrep` |
| AA458e | Trailing-slash artifact URL raises `ProvisionError` naming the URL; downloader not called; message is not `Is a directory` | unit | error — empty artifact name | `test_trailing_slash_url_is_refused_and_names_the_url` |
| AA458f | Empty last path segment never reaches `_download_pinned_url` | unit | error — refuse before I/O | `test_empty_artifact_name_is_refused_before_download` |
| AB467a | `parse_bandit_json` on empty / whitespace-only stdout returns `[]` (does not raise) | unit | happy — empty scan | `tests/analyzers/test_bandit_parse_467.py::test_empty_bandit_stdout_is_zero_findings_not_an_error` |
| AB467b | Adapter: empty bandit persisted stdout is `skipped=False`, zero findings (not "did not run") | integration | happy — empty scan | `test_empty_bandit_adapter_output_is_a_clean_scan_not_a_skip` |
| AB467c | Adapter: whitespace-only bandit stdout is a clean scan, not a skip | integration | edge — whitespace | `test_whitespace_bandit_adapter_output_is_a_clean_scan_not_a_skip` |
| AB467d | Adapter: unparsable bandit stdout skip reason includes a snippet of the first bytes | integration | error — garbage stdout | `test_garbage_bandit_stdout_skip_reason_includes_a_snippet` |
| AB467e | Catalog `bandit` command does not gain `-q` / `--quiet` (D3 forbids banner/`-q` as the fix) | unit | pin — not the fix | `test_bandit_catalog_command_does_not_add_quiet` |

Sibling: empty stdout still raises for other JSON-object parsers (`cargo-audit`, `knip`, `jscpd`, `bundler-audit`) in `tests/analyzers/parsers/test_auto_enabled_native.py::test_json_object_parser_raises_on_empty_stdout`. Non-empty garbage still raises for bandit there.

## Notes for the impl wave (D3)

Re-repro after `e66f8826` (2026-08-24): `parse_bandit_json("")` raises `ValueError: expected JSON object or array`. Adapter empty-file path classifies that as `skipped bandit: no output (analyzer did not run — likely sandbox unavailable outside CI)`. Garbage skip reason is `failed to parse analyzer output ({exc})` with no stdout snippet. Catalog command is `bandit -r --format json {files}` (no `-q`). Direct `uv run bandit -r --format json <py>` emits a JSON object on stdout; the banner/`-q` hypothesis is **disproved** — do not add `-q`.

- **Empty stdout:** treat as a clean scan (`[]` findings, `skipped=False`). Parser-level empty→`[]` is enough for the adapter empty-file path to stop taking the skip branch. Keep ruff's empty-output → "did not run" skip (`tests/analyzers/test_adapters_parse.py`) unchanged.
- **Garbage stdout:** stay skipped, but quote the first bytes of the unparsable output in `skip_reason` so a debugger sees what bandit emitted, not only the parser's expectation.
- **Do not** add `-q` / `--quiet` to `src/mergecraft/analyzers/catalog/bandit.yaml`.

## How to run (AB: expect FAIL until impl)

```bash
cd /Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/analyzers/test_bandit_parse_467.py -q
make lint
```

## Out of scope

AC #469, AD #466, AE #459, AF #460, AG #464, AH #485. Product code under `src/mergecraft/`. B/C files (`cli/app.py`, `.github/workflows/mergecraft.yml`, `finding.py`, `cli/auth_cmd.py`).
