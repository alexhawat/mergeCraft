# Test plan — open-issues-sweep-2026-08-24-a (AA #458 only)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-a-analyzers-ci-wave-plan.md`
Worktree: `/Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a`
Branch: `wave/open-issues-sweep-2026-08-24-a`
Issue: [#458](https://github.com/alexhawat/mergeCraft/issues/458)

Authoring: **AA RED** (this document). Implementation: AA impl (D2). AB–AH not authored here.

## xfail schedule

None. AA contracts are the next impl wave; tests are **plain FAIL** until D2 lands. Do not `xfail` (would hide RED).

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AA458a | `validate_manifest(..., check_provenance=True)` rejects sha256 of 64 zero hex digits | unit | error — placeholder pin | `tests/analyzers/test_placeholder_provenance_458.py::test_validate_manifest_rejects_all_zero_sha256_pin` |
| AA458b | Empty `provenance: {}` and a real (non-zero) pin still validate | unit | happy | `test_validate_manifest_accepts_empty_provenance_and_real_pin` |
| AA458c | `validate_manifest_ship_gate` (`make catalog-check` path) rejects an all-zero pin when fixture + doc row exist | functional | error — catalog-check | `test_catalog_ship_gate_rejects_all_zero_sha256` |
| AA458d | Shipped `checkov` / `yamllint` YAML is `provenance: {}` like `semgrep` | unit | happy — catalog pins | `test_checkov_and_yamllint_ship_empty_provenance_like_semgrep` |
| AA458e | Trailing-slash artifact URL raises `ProvisionError` naming the URL; downloader not called; message is not `Is a directory` | unit | error — empty artifact name | `test_trailing_slash_url_is_refused_and_names_the_url` |
| AA458f | Empty last path segment never reaches `_download_pinned_url` | unit | error — refuse before I/O | `test_empty_artifact_name_is_refused_before_download` |

## Notes for the impl wave (D2)

- **Catalog-check:** reject all-zero `sha256` in `validate_manifest` (when `check_provenance=True`) **and** wire that into `validate_manifest_ship_gate` / `validate_catalog` so `make catalog-check` fails a placeholder pin. Message should mention `sha256` / placeholder / all-zero.
- **Shipped YAML:** set `checkov.yaml` and `yamllint.yaml` to `provenance: {}` (semgrep). Other catalog files still carry all-zero pins; applying the new check to `validate_catalog()` will fail those until they also become `{}` or real pins. Impl should either convert the remaining pip-style placeholders or keep the live catalog green by converting every all-zero pin the gate will see.
- **Provision:** if `url.rsplit("/", 1)[-1]` is empty (trailing slash), raise `ProvisionError` naming the URL **before** `_download_pinned_url`. Do not write the temp directory as the artifact (`Is a directory`).

## How to run (expect FAIL until impl)

```bash
cd /Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/analyzers/test_placeholder_provenance_458.py -q
make lint
```

## Out of scope

AB #467, AC #469, AD #466, AE #459, AF #460, AG #464, AH #485. Product code under `src/mergecraft/`. B/C files (`cli/app.py`, `.github/workflows/mergecraft.yml`, `finding.py`, `cli/auth_cmd.py`).
