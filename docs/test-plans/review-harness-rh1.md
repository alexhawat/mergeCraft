# Review harness RH1 — fixture schema and strict matcher — test plan

Wave plan: `.ignorelocal/waves/06-review-harness-wave-plan.md` (PR RH1)
Worktree: `../mergecraft-review-harness` @ `wave/review-harness`
Authoring wave: **RH1.1** (tests-first — this file). Implementation: **RH1.2**.
xfail-reconciliation: **post-RH1.2**.

RH1 pins a test-only provider fixture schema, strict request matcher, and
redacted mismatch diagnostics under `tests/support/provider_harness/`. Tests
live in `tests/harness/`. Zero `src/mergecraft/` edits (**D2**).

Target API (RH1.2):

- `tests.support.provider_harness.schema` — Pydantic `MatchSpec`, `ResponseBlock`,
  `ResponseSpec`, `FixtureSpec`, `load_fixture_file(path) -> FixtureSpec`,
  `MalformedFixtureError`.
- `tests.support.provider_harness.matcher` — `match_fixture(request, fixtures, *,
  strict=True) -> FixtureSpec`; errors `NoFixtureMatch`, `AmbiguousFixtureMatch`,
  `FixtureReuseError`.
- `tests.support.provider_harness.diagnostics` — `format_mismatch(...)` bounded,
  redacted string with candidate fail reasons.

## xfail schedule

All RH1.2 markers use `strict=False` (`pyproject.toml` may set `xfail_strict =
true`; an early-passing xfail becomes XPASS, not a silent pass). **Cleared after
RH1.2** — twelve contract tests become real passes; three regression pins were
never marked.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **RH1.2** | `test_fixture_requires_provider_and_model` | `green after RH1.2` | pending |
| **RH1.2** | `test_fixture_requires_request_match_fields` | same | pending |
| **RH1.2** | `test_fixture_accepts_json_response_and_metadata` | same | pending |
| **RH1.2** | `test_fixture_accepts_ordered_response_blocks` | same | pending |
| **RH1.2** | `test_malformed_fixture_is_rejected_with_path` | same | pending |
| **RH1.2** | `test_matching_uses_provider_model_and_mode` | same | pending |
| **RH1.2** | `test_streaming_flag_participates_in_matching` | same | pending |
| **RH1.2** | `test_body_field_matchers_are_explicit` | same | pending |
| **RH1.2** | `test_no_fixture_match_is_an_error_in_strict_mode` | same | pending |
| **RH1.2** | `test_multiple_matches_are_an_error` | same | pending |
| **RH1.2** | `test_unexpected_fixture_reuse_is_an_error` | same | pending |
| **RH1.2** | `test_mismatch_includes_redacted_request_and_candidate_reasons` | same | pending |

Regression pins (no xfail — must pass @ RH1.1):

| Test | Contract |
|------|----------|
| `test_lenient_mode_is_not_the_ci_default` | D7/D16 — `MERGECRAFT_PROVIDER_HARNESS_LENIENT` absent from `pyproject.toml` `addopts` and `tests/conftest.py` |
| `test_diagnostics_do_not_include_provider_keys_or_github_tokens` | D14 — existing `redact_secrets` removes `sk-…` and `ghp_…` samples |
| `test_src_mergecraft_does_not_import_provider_harness` | D2 — AST scan: no `src/mergecraft/**/*.py` imports `tests.support.provider_harness` |

## Contract matrix

| # | Decision | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| RH1.1a | D17 — JSON fixture schema | unit | happy: metadata + JSON body | `test_fixture_accepts_json_response_and_metadata` |
| RH1.1b | D17 — ordered blocks | unit | happy: text + tool_call blocks | `test_fixture_accepts_ordered_response_blocks` |
| RH1.1c | D17 — required match fields | unit | error: missing provider/model | `test_fixture_requires_provider_and_model`, `test_fixture_requires_request_match_fields` |
| RH1.1d | D17 — malformed file | unit | error: invalid JSON names path | `test_malformed_fixture_is_rejected_with_path` |
| RH1.1e | D7 — match dimensions | unit | happy: provider/model/mode | `test_matching_uses_provider_model_and_mode` |
| RH1.1f | D7 — streaming flag | unit | happy: streaming True/False | `test_streaming_flag_participates_in_matching` |
| RH1.1g | D7 — body_fields | unit | happy + error: explicit equality | `test_body_field_matchers_are_explicit` |
| RH1.1h | D7 — strict no-match | unit | error: `NoFixtureMatch` | `test_no_fixture_match_is_an_error_in_strict_mode` |
| RH1.1i | D7 — ambiguous match | unit | error: `AmbiguousFixtureMatch` | `test_multiple_matches_are_an_error` |
| RH1.1j | D7 — reuse policy | unit | error: default `max_uses=1` | `test_unexpected_fixture_reuse_is_an_error` |
| RH1.1k | D14 — redacted diagnostics | integration | mismatch string redacts key, lists candidates | `test_mismatch_includes_redacted_request_and_candidate_reasons` |
| RH1.1l | D16 — lenient not CI default | pin | env var absent from pytest defaults | `test_lenient_mode_is_not_the_ci_default` |
| RH1.1m | D14 — redaction pin | pin | `redact_secrets` contract | `test_diagnostics_do_not_include_provider_keys_or_github_tokens` |
| RH1.1n | D2 — production fence | pin | no prod import of harness | `test_src_mergecraft_does_not_import_provider_harness` |

## RED acceptance (RH1.1)

- `uv run pytest --collect-only -q tests/harness/` → **15** collected, zero collection errors.
- File run: **3 pass** (lenient pin, redaction pin, import fence) + **12 xfail** (schema,
  matcher, diagnostics). Do not edit `tests/support/provider_harness/` or `src/` to green
  the suite in RH1.1.

## Files

| Path | Role |
|------|------|
| `tests/harness/test_fixture_schema.py` | Pydantic schema + `load_fixture_file` |
| `tests/harness/test_fixture_matcher.py` | `match_fixture` strict matching |
| `tests/harness/test_diagnostics.py` | `format_mismatch` + redaction pin |
| `tests/harness/test_production_import_fence.py` | D2 import fence |
| `tests/harness/_helpers.py` | Shared request snapshot builder |

Implementation lands in RH1.2 under `tests/support/provider_harness/{schema,matcher,diagnostics}.py`
and `tests/harness/fixtures/schema-smoke.json`.
