# Test plan — open-issues-sweep-2026-08-24-a (AA–AG GREEN + AH #485 RED)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-a-analyzers-ci-wave-plan.md`
Worktree: `/Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a`
Branch: `wave/open-issues-sweep-2026-08-24-a`
Issues: [#458](https://github.com/alexhawat/mergeCraft/issues/458), [#467](https://github.com/alexhawat/mergeCraft/issues/467), [#469](https://github.com/alexhawat/mergeCraft/issues/469), [#466](https://github.com/alexhawat/mergeCraft/issues/466), [#459](https://github.com/alexhawat/mergeCraft/issues/459), [#460](https://github.com/alexhawat/mergeCraft/issues/460), [#464](https://github.com/alexhawat/mergeCraft/issues/464), [#485](https://github.com/alexhawat/mergeCraft/issues/485)

Authoring: **AA–AG GREEN**. **AH RED** (this update). Implementation: AH impl (D9). Final not authored here.

## xfail schedule

None. AH contracts are the next impl wave; tests are **plain FAIL** until D9 lands. Do not `xfail` (would hide RED). Either D9 fork greens the XOR tests — do not pick a fork in the tests.

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
| AE459a | `catalog_scan_status(ran=False, findings=[])` is `unavailable`, not `clean` | unit | error — skipped catalog | `tests/analyzers/test_skipped_catalog_reporting_459.py::test_skipped_catalog_status_is_unavailable_not_clean` |
| AE459b | `ran=True` + zero findings is `clean` | unit | happy — clean scan | `test_ran_true_zero_findings_is_a_clean_scan` |
| AE459c | Disabled / no-match / empty-row `ran=False` is still `unavailable` | unit | edge — no tool rows | `test_ran_false_without_tool_rows_is_still_unavailable` |
| AE459d | Mixed passed + skipped is not catalog `unavailable` | unit | edge — partial run | `test_mixed_passed_and_skipped_is_not_unavailable` |
| AE459e | Same-repo `pull_request_target` stays `untrusted` (do not grant `trusted`) | unit | pin — trust tier | `test_pull_request_target_never_grants_trusted` |
| AE459f | `run_analyzers` payload `reason` names unavailable when the catalog did not run | functional | error — MCP payload | `test_run_analyzers_payload_names_unavailable_when_catalog_skipped` |
| AE459g | Catalog log says unavailable (not glanceable `findings=0` clean) | functional | error — log line | `test_run_analyzers_log_is_unavailable_not_findings_zero_clean` |
| AE459h | Check-run summary states `analyzers: unavailable` once, not 13 skip lines | integration | error — check-run | `tests/utils/test_skipped_catalog_surfaces_459.py::test_check_run_states_skipped_catalog_as_unavailable_once` |
| AE459i | A clean scan's check-run does not claim catalog unavailable | integration | happy — contrast | `test_check_run_clean_scan_does_not_claim_unavailable` |
| AE459j | Packet has one `name=analyzers` deterministic check with `status=unavailable` | integration | error — packet | `test_packet_states_skipped_catalog_as_unavailable_not_clean` |
| AE459k | Packet clean scan does not mark catalog unavailable | integration | happy — contrast | `test_packet_clean_scan_does_not_mark_catalog_unavailable` |

| AF460a | `build_run_packet` includes agent findings; `decide_approval(packet)` is `failure` for agent Critical/Major | unit | happy — agent blocker | `tests/agents/test_approval_gate_agent_findings_460.py::test_packet_from_run_carries_agent_blocker_into_decide_approval` |
| AF460b | Packet `decision.action` is `request_changes` when the agent raised a blocker | unit | happy — packet action | `test_packet_request_changes_for_agent_blocker` |
| AF460c | Packet unions agent + analyzer findings; CI not required | unit | happy — union | `test_packet_unions_agent_and_analyzer_findings` |
| AF460d | Trusted + succeeded + empty findings stays `neutral` (not silent success) | unit | pin — empty-list guard | `test_empty_findings_stay_neutral_not_success` |
| AF460e | Untrusted tier never `success` even with an agent Minor | unit | pin — untrusted guard | `test_untrusted_tier_never_succeeds_even_with_agent_minor` |
| AF460f | `report_status_checks` posts `mergecraft-approval` `failure` for agent Critical/Major | functional | happy — check-run | `tests/utils/test_approval_check_agent_findings_460.py::test_agent_blocker_makes_approval_check_failure` |
| AF460g | Packet `request_changes` and check `failure` agree | integration | happy — match | `test_packet_request_changes_matches_approval_check` |
| AF460h | Empty analyzer list + agent Major still fails the check (not findings=0 freeze) | integration | error — #460 log shape | `test_gate_reads_agent_findings_when_analyzer_list_is_empty` |
| AF460i | Analyzer Major still fails the gate | integration | pin — analyzer path | `test_analyzer_major_still_fails_the_gate` |
| AF460j | Empty findings do not silently succeed on the check | functional | pin — empty-list guard | `test_empty_findings_do_not_silently_succeed` |
| AF460k | Untrusted check never `success` | functional | pin — untrusted guard | `test_untrusted_tier_does_not_silently_succeed` |
| AG464a | SARIF `error` from ruff/mypy/bandit keeps Critical/Major (not clamped) | unit | happy — uncap | `tests/ci/test_ci_sarif_evidence_464.py::test_error_level_ci_sarif_keeps_blocking_severity` |
| AG464b | SARIF `warning` stays non-blocking | unit | edge — warning | `test_warning_level_ci_sarif_stays_non_blocking` |
| AG464c | Failed check-run finding stays non-blocking (D11 pin) | unit | pin — check run | `test_check_run_finding_stays_non_blocking` |
| AG464d | Empty SARIF is zero findings | unit | edge — empty | `test_empty_sarif_is_zero_findings` |
| AG464e | Recorded CI SARIF is readable from tool state at blocking severity | integration | happy — record | `test_record_ci_sarif_is_readable_from_tool_state` |
| AG464f | `collect_ci_sarif_findings` ingests declared `ruff-sarif` zip; error stays blocking | integration | happy — ingest | `test_collect_ingests_declared_ruff_sarif_artifact` |
| AG464g | Undeclared artifact is ignored | integration | edge — undeclared | `test_collect_ignores_undeclared_artifact` |
| AG464h | Empty `ciEvidence` makes no GitHub API call | integration | pin — opt-in | `test_collect_makes_no_api_call_when_ci_evidence_is_empty` |
| AG464i | Artifact download failure is swallowed (no raise) | error | ingest failure | `test_collect_swallows_artifact_download_failure` |
| AG464j | `RepoSettings` accepts first-wave `ciEvidence.sarifArtifacts` | unit | happy — settings | `test_settings_accept_first_wave_sarif_artifacts` |
| AG464k | Dogfood config enables ruff/mypy/bandit SARIF only | functional | happy — enable | `test_dogfood_config_enables_first_wave_ci_evidence` |
| AG464l | `ci.yml` uploads `ruff-sarif` / `mypy-sarif` / `bandit-sarif` | functional | happy — CI upload | `test_ci_yml_uploads_first_wave_sarif` |
| AG464m | Makefile still runs ruff, mypy, bandit | pin | first wave tools | `test_makefile_first_wave_tools_still_run` |
| AG464n | `mergecraft.yml` is not the SARIF upload surface | pin — B/C | do not steal | `test_mergecraft_yml_is_not_the_sarif_upload_surface` |
| AG464o | Packet includes CI ruff SARIF; `decide_approval` is `failure` | unit | happy — gate | `tests/agents/test_approval_gate_ci_sarif_464.py::test_packet_from_ci_ruff_sarif_fails_decide_approval` |
| AG464p | Packet `action=request_changes` for CI ruff SARIF | unit | happy — packet action | `test_packet_request_changes_for_ci_ruff_sarif` |
| AG464q | Empty CI evidence stays `neutral` | unit | pin — empty-list | `test_empty_ci_evidence_stays_neutral` |
| AG464r | Untrusted never `success` with CI ruff SARIF | unit | pin — untrusted | `test_untrusted_never_succeeds_with_ci_ruff_sarif` |
| AG464s | `report_status_checks` posts `mergecraft-approval` `failure` for CI ruff SARIF | functional | happy — check-run | `tests/utils/test_approval_check_ci_sarif_464.py::test_ruff_ci_sarif_makes_approval_check_failure` |
| AG464t | Packet `request_changes` matches check `failure` | integration | happy — match | `test_packet_request_changes_matches_ci_sarif_approval_check` |
| AG464u | Warning-level CI SARIF does not fail the gate | functional | edge — warning | `test_warning_ci_sarif_does_not_fail_the_gate` |
| AG464v | Empty CI evidence does not silently succeed | functional | pin — empty-list | `test_empty_ci_evidence_does_not_silently_succeed` |
| AG464w | Untrusted check never `success` with CI SARIF | functional | pin — untrusted | `test_untrusted_tier_does_not_succeed_with_ci_sarif` |
| AH485a | Attribution (1): base already below floor is inherited, not caused | unit | happy — (1) | `tests/ci/test_coverage_inherited_drift_485.py::test_attribution_1_base_below_floor_is_inherited` |
| AH485b | Attribution (2): drop that stays at/above floor is caused and non-fatal | unit | happy — (2) | `test_attribution_2_drop_staying_above_floor_is_caused_and_non_fatal` |
| AH485c | Below-floor drop shallower than 1.0pp margin stays caused under both D9 forks | unit | edge — (2) | `test_attribution_2_drop_shallower_than_margin_stays_caused` |
| AH485d | Head == base above floor is neither inherited nor caused | unit | edge — OK | `test_equal_coverage_above_floor_is_ok` |
| AH485e | Missing coverage report raises FileNotFoundError naming the path | unit | error | `test_missing_coverage_report_raises_file_not_found` |
| AH485f | D9 XOR: fixture hits inherited-drift (3) while the margin constant exists, or constant+dead branch are gone and (1)(2) remain | unit | D9 — either fork | `test_d9_inherited_drift_is_reachable_or_dead_branch_and_constant_removed` |
| AH485g | `main()` exit 1 for the D9 fixture; CLI text follows the chosen fork | functional | D9 — CLI | `test_d9_cli_matches_inherited_drift_or_caused_remaining_attribution` |
| AH485h | `inherited` and `caused_by_change` never both True (no third attribution) | unit | pin — D9 | `test_no_third_attribution_flags` |
| AH485i | Exit-policy suite does not lock (2)-before-(3) order | unit | pin — both forks | `tests/ci/test_coverage_delta_exit_policy.py::test_compare_to_base_marks_shallower_than_margin_drop_below_floor_as_caused` |

Sibling: empty stdout still raises for other JSON-object parsers (`cargo-audit`, `knip`, `jscpd`, `bundler-audit`) in `tests/analyzers/parsers/test_auto_enabled_native.py::test_json_object_parser_raises_on_empty_stdout`. Non-empty garbage still raises for bandit there. `tests/ci/test_evidence.py::test_ci_sarif_findings_are_never_blamed_on_this_pr` still pins `introduced_by_pr=unknown`; it no longer asserts a non-blocking severity cap.

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

## Notes for the impl wave (D6)

Re-repro (2026-08-24): self-review log on PR #457 is `analyzers: ran=False tools=13 findings=0`. Every tool is skipped (trust tier, sandbox, or provision). `findings=0` reads like a clean scan. Check-run completion is "The mergeCraft run finished successfully."; approval decision lines include `Findings: 0`. Packet `_deterministic_checks` copies per-tool `unavailable` rows but has no catalog-level glanceable row. `derive_trust_tier` already refuses `trusted` on `pull_request_target` (keep that).

- **Label:** add `catalog_scan_status` on `src/mergecraft/analyzers/pipeline.py`. `ran=False` → `"unavailable"`. `ran=True` and no findings → `"clean"`. A mixed passed+skipped run is not catalog unavailable.
- **Loud once:** check-run summary (completion and/or approval) must contain `analyzers: unavailable` (or `analyzer: unavailable`). Do not dump all 13 skip reasons into the check-run. Packet: one `DeterministicCheck(name="analyzers", status="unavailable")` in addition to per-tool rows.
- **MCP:** `run_analyzers` `reason` and the catalog log line must say unavailable. Do not present `findings=0` as the glanceable signal.
- **Do not** grant `trusted` on `pull_request_target`. Do not run catalog tools in the privileged Action job. Participation is #464 / AG (CI SARIF). Do not change the approval-gate conclusion contract (that is #460 / AF).


## Notes for the impl wave (D7)

Re-repro (2026-08-24): `report_status_checks` loads `_load_structural_findings` from `tool_state.analyzer_run.findings` only. With `agent_findings` holding a Critical Finding dump and an empty skipped catalog, the approval check is `neutral` (`findings=0`). `build_run_packet` uses the same loader, so `packet.findings` is empty and `decision.verdict` is `neutral` with `action=block` (schema-failure default), not `request_changes`.

`decide_approval(packet)` already returns `failure` when the packet *already contains* agent Critical/Major findings. The gap is assembling that packet (and the check) from the findings the review produced.

- **Consume review findings:** agent (`tool_state.agent_findings`) + analyzer (`analyzer_run.findings`). Prefer `decide_approval` on the `MergeEvidencePacket` already built in `agents/gates.py` / `build_run_packet`.
- **Wire the check:** `mergecraft-approval` `failure` when the agent raised Critical or Major, even if the catalog did not run.
- **Match the packet:** `decision.verdict=failure` and `decision.action=request_changes` must agree with the check conclusion.
- **Guards stay:** empty findings on trusted → `neutral` (not `success`). Untrusted → never `success`.
- **Do not** ingest CI SARIF here (AG #464 / D8). Do not diagnose 422 inline comments or dual-verdict / `semantic_rejection`.

## Notes for the impl wave (D8)

Re-repro (2026-08-24): `sarif_findings` restamps every CI SARIF result through `_as_unblamed_ci_finding`, which clamps severity to `Minor` unless it is already `Minor`/`Trivial`. A ruff SARIF `error` therefore never reaches `BLOCKING_SEVERITIES` (`Critical`, `Major`). After AF, `build_run_packet` already unions `ci_evidence_findings` and `report_status_checks` calls `decide_approval` on that packet — so a clamped Minor CI finding is recorded (`source=ci`) and the approval check can still conclude `success`. D8 is: keep the native blocking grade, ship SARIF artifacts from `ci.yml` for ruff/mypy/bandit, enable `ciEvidence.sarifArtifacts` in dogfood config, and let that ruff error fail the gate.

- **Uncap SARIF errors:** a SARIF `error` from `ruff-sarif` / `mypy-sarif` / `bandit-sarif` must stay `Major` (or `Critical`). Do not clamp every CI finding to non-blocking. Attribution may stay `introduced_by_pr=unknown` until blame speaks. A SARIF `warning` and a bare failed check-run stay non-blocking (D11 pin).
- **Ingest:** `collect_ci_sarif_findings` already downloads declared workflow artifacts. Keep opt-in (empty `ci_sarif_artifacts` → no API call). Swallow download/parse failures. Ignore undeclared artifact names. First wave only: `ruff-sarif`, `mypy-sarif`, `bandit-sarif` — do not port the rest of the catalog.
- **Enable:** additive `ciEvidence.sarifArtifacts` on `config/settings.py` already exists. Dogfood `.mergecraft/config.yaml` must list the three first-wave names. `ci.yml` (not `mergecraft.yml`) must upload those artifacts. B/C own `mergecraft.yml`.
- **Gate:** after uncap, packet `decide_approval` is `failure` / `request_changes` and `mergecraft-approval` is `failure` for a ruff CI SARIF error even when the in-job catalog did not run. Empty-list stays `neutral`. Untrusted never `success`.
- **Do not** invent blame or satisfied-by-CI waves (issue AC is wider; D8 wins). Do not grant `trusted` on `pull_request_target`. Do not run catalog tools in the privileged Action job.

## Notes for the impl wave (D9)

Owner: `scripts/check_coverage_delta.py`. Today attribution (3) is dead: `compare_to_base` returns caused when `head < base` before `INHERITED_BREACH_MARGIN` can run. With base at the floor and head ≥ 1.0pp below the floor, current classification is caused (2).

**Fork A (reorder):** keep `INHERITED_BREACH_MARGIN` (or `INHERITED_DRIFT_THRESHOLD`). Reorder so the D9 fixture (`floor=82`, `base=82`, `head=80.5`) sets `inherited=True`, `caused_by_change=False`, and the message is inherited-drift (not “base branch … below floor”). `main()` exits 1 and stdout/stderr mention inherited. Do not invent a third attribution.

**Fork B (delete):** remove the dead branch and the constant. The same fixture stays caused (2). `compare_to_base` has exactly one `inherited=True` (attribution 1). (1) and (2) tests stay green.

A below-floor drop shallower than 1.0pp (`83 → 81.5`, floor `82`) stays caused under **both** forks. Do not restore a test that requires (2) to run before (3) on a ≥-margin drop — that locked the dead order.

Do not implement a third attribution class.

## How to run (AH: expect FAIL until impl)

```bash
cd /Users/alex/Documents/code/sevn.bot/mergecraft-open-issues-sweep-2026-08-24-a
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/ci/test_coverage_inherited_drift_485.py tests/ci/test_coverage_delta_exit_policy.py -q
make lint
make typecheck
```

Expect RED until D9: two XOR tests fail while `INHERITED_BREACH_MARGIN` exists and the fixture is classified caused. Attributions (1)(2), OK, missing-file, no-third-class, and the shallower-than-margin exit-policy case already pass.

## Out of scope

AH product impl (this update is tests only). Weakening `pull_request_target` trust. Running analyzers inside the privileged Action job. B/C files (`cli/app.py`, `.github/workflows/mergecraft.yml`, `finding.py`, `cli/auth_cmd.py`). Blame / satisfied-by-CI. 422 / dual-verdict anomalies. A third coverage-delta attribution.
