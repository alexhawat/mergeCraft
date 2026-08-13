# Release gating + supply chain — test plan (W1-RED)

Wave plan: `.ignorelocal/issues-release-gating-supply-chain-wave-plan.md`
Worktree: `mergecraft-rls-gating-supply-chain` @ `feat/rls-gating-supply-chain`
Authoring wave: **W1-RED** (entire suite for plan waves W2–W9; implementation
waves turn it green). S5 (#145) has landed — W9 xfails are `green after W9`,
not a D19 spin-out.

## Locked decisions (D-table rows that bind this suite)

| # | Topic | Bound tests |
|---|-------|-------------|
| **D4** | E2E is a reusable workflow (`workflow_call`) | `tests/ci/test_e2e_release_gate.py::test_e2e_yml_on_includes_workflow_call` |
| **D5** | Gate `build-images`, not only `promote` | `test_build_images_needs_e2e_gate`, `test_removing_e2e_gate_from_build_images_needs_fails` |
| **D6** | Blocking scan on every promoting ref | `tests/ci/test_trivy_scan_gate.py::test_scan_gate_blocks_every_ref_that_can_publish`; promote-on-main pin stays green |
| **D7** | `.trivyignore` CVE + justification + expiry | `test_trivyignore_exists_with_required_header_schema`, `test_expiry_checker_fails_on_past_dated_entry` |
| **D9** | Missing creds fail on schedule, inert on PR | `tests/ci/test_live_provider_matrix.py`, `tests/integration/test_live_providers.py::test_missing_credential_fails_on_schedule` |
| **D10** | Per-provider matrix, `fail-fast: false` | `test_live_matrix_fail_fast_false`, `test_each_matrix_leg_gets_only_its_own_provider_secret` |
| **D11** | `build-dist` is not E2E-gated | `test_build_dist_does_not_need_e2e_gate` |
| **D13** | No coverage badge required | no README-badge assertion (intentionally absent) |
| **D14** | Docs badge label matches Pages URL | `tests/docs/test_distribution_checklist.py::test_docs_badge_label_matches_live_github_pages_url` |
| **D15** | Do not rename `src/mergecraft/yes/` | `test_yes_package_not_renamed_unless_d15_allows` (plain — default holds today) |
| **D16** | Python `>=3.14` stays hard | `test_python_314_requirement_documented` |
| **D17** | Assets named, not invented | `test_docs_assets_readme_names_required_binaries` |
| **D18** | Structured completion, not HTTP 200 | `tests/integration/test_live_providers.py` + `StreamSpanAccumulator` |
| **D19** | W9 spin-out | unused (S5 landed); xfails stay `green after W9` |

## xfail / RED schedule

All cross-wave markers are **non-strict** (`strict=False`). The repo sets
`xfail_strict = true` globally.

| Plan wave | Test files | Marker reason prefix |
|-----------|------------|----------------------|
| **W2** | *(reconciled)* `tests/ci/test_e2e_release_gate.py` — xfails dropped; real passes | — |
| **W3** | `tests/ci/test_trivy_scan_gate.py` (except promote-on-main pin) | `green after W3:` |
| **W4** | `tests/ci/test_live_provider_matrix.py` (selector / fail-loud / matrix); `tests/integration/test_live_providers.py`; `tests/integration/test_github_integration.py` | `green after W4:` |
| **W5** | `tests/docs/test_distribution_checklist.py` (except D15 yes/ pin) | `green after W5:` |
| **W6** | `tests/ci/test_coverage_ratchet.py` | `green after W6:` |
| **W7** | `tests/tracing/test_otlp_collector_e2e.py` (except SHA-pin) | `green after W7:` |
| **W8** | `tests/ci/test_ruff_advisory_families.py` | `green after W8:` |
| **W9** | `tests/evals/test_benchmark_publication.py` (except S5 helper pin) | `green after W9:` |

### Already green (regression pins — no xfail)

| Test | Why it can pass on W1 HEAD |
|------|----------------------------|
| `tests/ci/test_e2e_release_gate.py` (all eight cases) | W2 landed `workflow_call` + `e2e-gate`; xfails dropped |
| `test_touched_workflows_third_party_uses_are_sha_pinned` | convention 2 already holds |
| `test_w7_touched_workflows_remain_sha_pinned` | same |
| `test_promote_still_fires_on_main_and_pre_001` | D6 must not strip `:latest` publish |
| `test_live_marker_registered_in_pytest_ini` | `live` marker already in `pyproject.toml` |
| `test_suite_is_inert_on_pull_request` (YAML) | `integration-live` already skips `pull_request` |
| `test_no_skips_when_no_secret_test_exists` | audit-escape meta-guard |
| `test_yes_package_not_renamed_unless_d15_allows` | D15 default |
| `test_s5_prompt_version_helper_is_available` | S5 (#145) merged |

## Contract → coverage matrix

### W2 — E2E gates published images (R-F1) — green after W2 impl (`b47abef`) + xfail recon

| Contract | Layer | Happy / edge / error | Tests |
|----------|-------|----------------------|-------|
| `e2e.yml` `on:` includes `workflow_call` | unit (YAML) | keeps PR / schedule / dispatch | `test_e2e_yml_on_includes_workflow_call` |
| `e2e-gate` job `needs: verify`, `uses:` local workflow | unit | missing job | `test_ci_cd_has_e2e_gate_job` |
| secrets via `secrets:` never `with:` | unit | secret-shaped inputs | `test_e2e_gate_passes_secrets_not_as_inputs` |
| `build-images.needs` includes `e2e-gate` | unit | **guard-deletion** | `test_build_images_needs_e2e_gate`, `test_removing_e2e_gate_from_build_images_needs_fails` |
| `build-dist` does not need `e2e-gate` | unit | D11 | `test_build_dist_does_not_need_e2e_gate` |
| third-party `uses:` 40-hex SHA | unit | tag pins | `test_touched_workflows_third_party_uses_are_sha_pinned` |

### W3 — blocking scan + expiring waivers (R-F2)

| Contract | Layer | Coverage | Tests |
|----------|-------|----------|-------|
| Scan blocks promoting refs | unit (YAML script) | unconditional `exit_code=1` **or** `main` + `pre-0.0.1` | `test_scan_gate_blocks_every_ref_that_can_publish` |
| `.trivyignore` schema | unit | header; CVE entries need justification + expiry | `test_trivyignore_exists_with_required_header_schema` |
| Expiry checker | unit | past date fails (**guard-deletion**); future ok; bare CVE invalid | `test_expiry_checker_*`, `test_trivyignore_schema_rejects_entry_without_justification_or_expiry` |
| Waiver docs | unit | `docs/supply-chain.md` or CONTRIBUTING section | `test_waiver_docs_exist` |
| Promote refs unchanged | unit | D6 alternative not taken | `test_promote_still_fires_on_main_and_pre_001` |

Named deliverable: `scripts/check_trivyignore_expiry.py` (`check_trivyignore` or `main`).

### W4 — live provider matrix (R-F3)

| Contract | Layer | Coverage | Tests |
|----------|-------|----------|-------|
| `live` marker registered | unit | pyproject | `test_live_marker_registered_in_pytest_ini` |
| `test-integration-live` selects `-m live` | unit (Makefile) | not `-m integration` | `test_test_integration_live_selects_live_marker` |
| Missing creds fail on schedule | unit + live | **no** `test_…_skips_when_no_secret`; Makefile must not `exit 0` | `test_missing_credential_fails_on_schedule` (both files) |
| Inert on `pull_request` | unit + live | YAML `if:` + env | `test_suite_is_inert_on_pull_request` |
| Matrix `fail-fast: false` / one secret per leg | unit (YAML) | D10 | `test_live_matrix_fail_fast_false`, `test_each_matrix_leg_gets_only_its_own_provider_secret` |
| One structured completion per provider | live | Anthropic / OpenAI / Gemini / Nous → `StreamSpanAccumulator` | `test_*_minimal_completion` |
| Stream-consumer shape | unit/live | D18 | `test_response_shape_matches_stream_consumer_contract` |
| Token bound | unit | handful of tokens | `test_live_request_is_token_bounded` |
| GitHub roundtrip | live | checkout + `create_status`; concurrent same-token posts | `tests/integration/test_github_integration.py::test_checkout_and_status_check_roundtrip` |

Live tests carry `@pytest.mark.live` **and** `@pytest.mark.integration` so
`make test` (`-m "not integration"`) does not call providers. Missing keys
`pytest.fail` — they do not skip. Live responses are not written to fixtures.

**Authoring note:** live-gate env was not used while writing this suite
(`skipped: no live credential` for execution; tests still authored).

### W5 — 0.0.1 distribution checklist (#141)

| Contract | Layer | Tests |
|----------|-------|-------|
| README drops `README-ideal.md` + two `TODO:` asset comments | unit | `test_readme_drops_ideal_and_todo_asset_comments` |
| Docs badge label matches Pages URL (D14) | unit | `test_docs_badge_label_matches_live_github_pages_url` |
| `docs/assets/README.md` names `logo.svg` / `demo.gif` | unit | `test_docs_assets_readme_names_required_binaries` |
| `docs/meat-spike.md` gone; `meat_python_plus/` gone or documented | unit | `test_prototype_residue_removed_or_documented` |
| `src/mergecraft/yes/` not renamed (D15) | unit | `test_yes_package_not_renamed_unless_d15_allows` |
| Python 3.14 + Docker path (D16) | unit | `test_python_314_requirement_documented` |

### W6 — coverage ratchet in `make ci` (#142 rescoped)

| Contract | Layer | Tests |
|----------|-------|-------|
| `make ci` graph includes `coverage-gate` | unit (Makefile) | `test_make_ci_graph_includes_coverage_gate` |
| Below floor fails | unit | `test_ratchet_fails_when_coverage_drops_below_floor` |
| Above floor+margin without bump fails (**guard-deletion**) | unit | `test_ratchet_fails_when_coverage_exceeds_floor_without_bump` |
| Within margin passes | unit | `test_ratchet_passes_within_margin` |

Named deliverable: `scripts/check_coverage_ratchet.py`. No README coverage-badge test (D13).

### W7 — real OTLP collector (#143)

| Contract | Layer | Tests |
|----------|-------|-------|
| Spans at `otel/opentelemetry-collector` with `gen_ai.*` | integration | `test_spans_arrive_at_real_collector_with_gen_ai_attributes` |
| One trace per run **against the collector** | integration | `test_one_trace_per_run_holds_against_the_collector` |
| Env / CLI / YAML → live sink | integration | `test_env_cli_yaml_precedence_resolves_to_live_sink` |
| Wrong endpoint fails the job | integration | `test_wrong_exporter_endpoint_fails_the_job` |
| Unguarded `set_tracer_provider` swallow | unit (source) | `test_unguarded_set_tracer_provider_swallow_would_fail_the_job` |
| Tracing disabled is a no-op | integration | `test_tracing_disabled_is_true_noop_no_collector_traffic` |
| Collector image digest-pinned; Make target exists | unit | `test_collector_image_is_digest_pinned_in_ci`, `test_make_target_invokes_collector_suite` |

These tests assert on `MERGECRAFT_OTEL_COLLECTOR_DUMP`, not
`MemorySink` / `_RecordingSpanProcessor`.

### W8 — ruff families (#146)

| Contract | Layer | Tests |
|----------|-------|-------|
| No family in both `select` and `ignore` | unit | `test_no_ruff_family_in_both_select_and_ignore` |
| Remaining selected former-advisory family is enforced | unit | `test_remaining_selected_family_is_enforced` (parametrized; drop from `select` is allowed) |

D21: if enforcing a family requires `tests/` churn, stop and re-dispatch test-creator.

### W9 — published benchmark numbers (#140)

| Contract | Layer | Tests |
|----------|-------|-------|
| README eval claim adjacent to dated precision/recall/F1 + FP-rate + corpus commit | unit | `test_readme_eval_claim_adjacent_to_dated_metrics_and_corpus_commit` |
| Replay target/job documented | unit | `test_replay_target_or_job_exists_and_is_documented` |
| Result set records `JudgePin`, `VERIFIER_RUBRIC_VERSION`, S5 `compute_prompt_version` | unit | `test_result_set_records_judge_pins_rubric_and_prompt_versions` |
| No placeholder numbers | unit | `test_published_metrics_are_not_placeholders` |
| S5 helper present | unit | `test_s5_prompt_version_helper_is_available` (plain) |

Do not invent metric values in tests. Named symbols: `compute_prompt_version`,
`JudgePin`, `judge_pin`, `VERIFIER_RUBRIC_VERSION`.

## Helpers

| Piece | Purpose |
|-------|---------|
| `tests/ci/workflow_support.py` | YAML load (`on:` → `True` key), `needs` list coercion, 40-hex `uses:` pin |

## xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-13 | W2 | `_W2` on six contracts in `tests/ci/test_e2e_release_gate.py` | SHA-pin cases were already unxfail'd; leave W3–W9 markers |

## Driving live / collector tests

- Provider completions use `httpx` against each provider's documented API, then
  fold the JSON body through `consume_stream` / `StreamSpanAccumulator`.
- GitHub roundtrip uses `GitHubClient.create_status` plus `asyncio.gather` on
  the same token.
- Collector tests read `MERGECRAFT_OTEL_COLLECTOR_DUMP` written by the real
  collector file exporter that W7 wires in CI.
