# Test plan — open-issues-sweep-2026-08-24-a (AA #458 + AB #467 + AC #469 + AD #466)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-a-analyzers-ci-wave-plan.md`
Worktree: `/Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a`
Branch: `wave/open-issues-sweep-2026-08-24-a`
Issues: [#458](https://github.com/alexhawat/mergeCraft/issues/458), [#467](https://github.com/alexhawat/mergeCraft/issues/467), [#469](https://github.com/alexhawat/mergeCraft/issues/469), [#466](https://github.com/alexhawat/mergeCraft/issues/466)

Authoring: **AA GREEN** (D2 landed). **AB GREEN** (D3 landed). **AC GREEN** (D4 landed). **AD RED** (this update). Implementation: AD impl (D5). AE–AH not authored here.

## xfail schedule

None. AD contracts are the next impl wave; tests are **plain FAIL** until D5 lands. Do not `xfail` (would hide RED).

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
| AC469a | `GitHubClient` owned-client headers omit `Authorization` when token is empty or whitespace | unit | error — empty token | `tests/utils/test_empty_github_bearer_469.py::test_github_client_omits_authorization_when_token_empty` |
| AC469b | `GitHubClient` still sets `Authorization: Bearer <token>` when a token is present | unit | happy | `test_github_client_sends_bearer_when_token_present` |
| AC469c | `get_commit_info` with empty token is `is_error`, names missing token, does not send HTTP | functional | error — offline skip | `test_get_commit_info_without_token_reports_unavailable_naming_token` |
| AC469d | `upload_file` with `MERGECRAFT_API_URL` set and empty/whitespace `api_token` does not send `Authorization: Bearer ` | integration | error — empty Bearer | `tests/mcp/test_empty_upload_bearer_469.py::test_upload_does_not_send_empty_bearer_when_api_url_set` |
| AC469e | Whitespace `api_token` does not interpolate `Bearer {token}` (same as empty) | integration | edge — whitespace | `test_upload_whitespace_token_does_not_interpolate_bearer` |
| AD466a | `classify_provider_failure` treats billing/credit/balance 404 as a different class from unknown-model 404 | unit | error — distinct classes | `tests/utils/test_nous_404_classification_466.py::TestNous404ClassesAreDistinct::test_billing_404_and_unknown_model_404_are_classified_separately` |
| AD466b | Generic HTTP 404 (not ``does not exist``) is not the unknown-model class | unit | edge — unstructured 404 | `test_generic_404_is_not_classified_as_unknown_model` |
| AD466c | Nous billing 404 JSON (`isRetryable: false`) is retryable for chain fail-over | unit | happy — fail-over | `TestNous404Failover::test_nous_billing_404_is_retryable_for_failover` |
| AD466d | Generic 404 without credits/balance/quota needles is retryable (needle-list-only cannot pass) | unit | pin — not needles-only | `test_generic_http_404_without_billing_prose_is_retryable_for_failover` |
| AD466e | Unknown-model 404 (``does not exist``) is not retryable / does not fail over | unit | error — config | `test_unknown_model_404_does_not_fail_over` |
| AD466f | Failed provider 404 with `output_schema` set is not rewritten as `schema_failure` / `set_output` | functional | error — surface provider | `TestProviderErrorNotSchemaFailure::test_failed_provider_404_is_not_rewritten_as_schema_failure` |
| AD466g | Successful agent without `set_output` still fails the schema check (do not delete the gate) | unit | pin — keep schema check | `test_successful_run_without_set_output_still_requires_schema` |
| AD466h | Nous billing 404 advances `run_with_model_chain` to the next slug | integration | happy — fail-over | `tests/integration/test_nous_404_failover_466.py::test_nous_billing_404_advances_the_model_chain` |
| AD466i | Generic (non-unknown-model) 404 advances the chain | integration | pin — not needles-only | `test_generic_404_that_is_not_unknown_model_advances_the_chain` |
| AD466j | Unknown-model 404 does not advance the chain; error is not `schema_failure` | integration | error — no fail-over | `test_unknown_model_404_does_not_fail_over` |

Sibling: empty stdout still raises for other JSON-object parsers (`cargo-audit`, `knip`, `jscpd`, `bundler-audit`) in `tests/analyzers/parsers/test_auto_enabled_native.py::test_json_object_parser_raises_on_empty_stdout`. Non-empty garbage still raises for bandit there.

## Notes for the impl wave (D3)

Re-repro after `e66f8826` (2026-08-24): `parse_bandit_json("")` raises `ValueError: expected JSON object or array`. Adapter empty-file path classifies that as `skipped bandit: no output (analyzer did not run — likely sandbox unavailable outside CI)`. Garbage skip reason is `failed to parse analyzer output ({exc})` with no stdout snippet. Catalog command is `bandit -r --format json {files}` (no `-q`). Direct `uv run bandit -r --format json <py>` emits a JSON object on stdout; the banner/`-q` hypothesis is **disproved** — do not add `-q`.

- **Empty stdout:** treat as a clean scan (`[]` findings, `skipped=False`). Parser-level empty→`[]` is enough for the adapter empty-file path to stop taking the skip branch. Keep ruff's empty-output → "did not run" skip (`tests/analyzers/test_adapters_parse.py`) unchanged.
- **Garbage stdout:** stay skipped, but quote the first bytes of the unparsable output in `skip_reason` so a debugger sees what bandit emitted, not only the parser's expectation.
- **Do not** add `-q` / `--quiet` to `src/mergecraft/analyzers/catalog/bandit.yaml`.

## Notes for the impl wave (D4)

Re-repro (2026-08-24): `GitHubClient("")` sets owned-client default header `Authorization: Bearer ` (trailing space). `get_commit_info` then calls `GitHubClient.request` / httpx, which raises `Illegal header value b'Bearer '` — the agent sees a library defect, not a missing credential. Offline `mergecraft review --diff` constructs `GitHubClient(token="")` by design.

`upload_file` (`src/mergecraft/mcp/upload.py`): empty `api_token` already takes the local `file://` stub when `MERGECRAFT_API_URL` is unset **or** token is falsy. A **whitespace** token is truthy, so the remote arm runs `Authorization: f"Bearer {ctx.api_token}"` and currently dies in SSRF/DNS (or would die in httpx on `Bearer `). Treat whitespace like empty: do not build `Authorization`.

- **`GitHubClient`:** omit the `Authorization` key when `token.strip()` is empty. Keep `Authorization: Bearer <token>` for a real token.
- **`get_commit_info` (offline / no token):** fail closed before HTTP with a message that names the missing token. Do not leak `Illegal header value`.
- **`upload_file`:** do not interpolate `Bearer {token}` when `api_token` is empty or whitespace. Local stub or an error naming the token are both acceptable; an empty Bearer header is not.

## Notes for the impl wave (D5)

Re-repro (2026-08-24): `_RETRYABLE_CLI_NEEDLES` has no `credits` / `balance`. `is_retryable_cli_failure` on the #466 Nous JSON (`statusCode: 404`, billing prose, `isRetryable: false`) returns False, so `_is_retryable_failure` does not advance the chain. Owner comment: the billing 404 was **factually false** (account funded). The bug is classification + `schema_failure` surface, not "out of credits".

`_promote_and_finalize_agent_result` raises `RuntimeError: output_schema was provided but agent did not call set_output` whenever `output_schema` is set and `tool_state.output` is empty — including when `AgentResult.success is False` and the agent never ran.

- **Classify separately:** add `classify_provider_failure` on `utils/retry_policy.py`. Billing/credit/balance 404 and unknown-model 404 (`does not exist`) must return different classes. A 404 that is not `does not exist` is retryable / fail-over even with no billing prose (so growing needles is not sufficient).
- **Wire fail-over:** `_is_retryable_failure` / `is_retryable_cli_failure` must treat billing 404 and generic (non-unknown-model) 404 as retryable for the chain. Provider `isRetryable: false` is wrong for chain purposes. Unknown-model 404 must not fail over.
- **Surface the provider error:** when the agent never ran (`success is False`), do not replace the provider message with the `set_output` / `schema_failure` RuntimeError. Keep the schema check for a successful run that skipped `set_output`.
- **Do not** expand D5 into "post-run retry re-calls the provider".
- **Do not** treat GitHub HTTP 404 retries as in-scope (`is_transient_http_error` stays 429/5xx).

## How to run (AD: expect FAIL until impl)

```bash
cd /Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/utils/test_nous_404_classification_466.py tests/integration/test_nous_404_failover_466.py -q
make lint
make typecheck
```

Expect **9 failed / 4 passed** until D5 (unknown-model 404 already does not fail over; successful run without `set_output` still hits the schema check).

## Out of scope

AE #459, AF #460, AG #464, AH #485. Product code under `src/mergecraft/`. B/C files (`cli/app.py`, `.github/workflows/mergecraft.yml`, `finding.py`, `cli/auth_cmd.py`). Post-run retry re-invoking the provider.
