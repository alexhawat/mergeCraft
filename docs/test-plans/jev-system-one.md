# Jev / System One — test plan

Wave plan: `.ignorelocal/waves/23-jev-system-one-wave-plan.md`
Worktree: `mc-jev` @ `wave/jev-system-one`
Authoring wave: **J1** (`test-creator`). Implementation: **J2–J5**. Final: **J6**.

Recorded TypeSafe envelopes live under `tests/jev/fixtures/transport/`. CI makes
zero live TypeSafe calls (D14). J0 live smoke is `skipped: no live credential`.

## J6.1 xfail reconciliation (2026-09-17)

J1 authored 92 cross-wave reds as `J2_XFAIL` / `J3_XFAIL` / `J4_XFAIL` /
`J5_XFAIL` (`strict=False`). J2–J5 XPASS'd all of them. This sweep deleted
those four markers and every decorator so **none remain**. The greening-wave
column below is historical. Suite end state: ordinary passing tests; 0
xfail / 0 xpass. J6 plan checkboxes stay ☐.

## Contract matrix

| Contract | Greening wave | Primary test(s) |
| --- | --- | --- |
| **J1.1** pin `jev-1.13.0` (D8) | J2 | `test_client.py::test_pinned_model_is_jev_1_13_0` |
| **J1.1** recorded call + latency | J2 | `…::test_call_sends_pinned_model_to_recorded_transport` |
| **J1.1** retry then success | J2 | `…::test_retry_on_transient_then_success` |
| **J1.1** permanent `TypeSafeAPIError` | J2 | `…::test_permanent_typesafe_error_does_not_retry` |
| **J1.1** 429 → retryable provider class | J2 | `…::test_rate_limit_maps_to_retryable_provider_failure` |
| **J1.1** `state is None` | J2 | `…::test_none_state_raises_structured_jev_error` |
| **J1.1** `enabled: false` skip (D4) | J2 | `…::test_disabled_settings_are_a_recorded_skip_not_a_failure` |
| **J1.1** credential-absent skip (G1–G3) | J2 | `…::test_enabled_without_credential_is_recorded_skip_not_silent_pass` |
| **J1.1** kill-switch stop (D10) | J2 | `…::test_kill_switch_stops_dispatch_and_records_the_stop` |
| **J1.1** concurrent same API key | J2 | `…::test_concurrent_same_api_key_shares_one_budget` |
| **J1.1** package exports | J2 | `…::test_package_exports_client_and_result_types` |
| **J1.1** price table / known cost | J2 | `test_cost.py::test_compute_cost_uses_price_table_when_tokens_known` |
| **J1.1** `input_tokens is None` (D10) | J2 | `test_cost.py::test_unreported_tokens_set_cost_known_false_not_zero` |
| **J1.1** client survives `Usage` None | J2 | `test_cost.py::test_client_survives_usage_input_tokens_none` |
| **J1.1** `jev:` default off | J2 | `test_settings.py::test_default_settings_jev_is_disabled` |
| **J1.1** floating alias rejected | J2 | `test_settings.py::test_jev_settings_model_cannot_be_floating_alias` |
| **J1.1** wire types | J2 | `test_types.py` |
| **J1.2** one GenAI span + `gen_ai.*` | J2 | `test_tracing.py::test_each_call_emits_one_genai_span` |
| **J1.2** Jev attrs under `mergecraft.*` (D9) | J2 | `…::test_jev_specific_attrs_live_under_mergecraft_not_gen_ai` |
| **J1.2** None usage not zeroed | J2 | `…::test_unreported_usage_does_not_zero_gen_ai_usage_attrs` |
| **J1.3** hunk + bounded context (D2) | J3 | `test_segment.py::test_segment_hunks_extracts_one_unit_with_bounded_context` |
| **J1.3** no function units | J3 | `…::test_function_units_are_out_of_scope` |
| **J1.3** stable unit ids | J3 | `…::test_unit_ids_are_stable_across_calls` |
| **J1.3** cache key `(hash, pack, model)` | J3 | `…::test_cache_key_covers_content_hash_pack_and_pinned_model` |
| **J1.3** empty / None / unicode | J3 | `…::test_empty_diff_yields_no_units`, `test_none_diff_raises_structured_error`, `test_unicode_paths_survive_segmentation` |
| **J1.3** analyzer residual | J3 | `…::test_analyzer_flagged_hunks_are_not_residual` |
| **J1.4** pack names/types (D1) | J3/J4/J5 | `test_questions.py` |
| **J1.4** no counting questions (D16) | J3 | `…::test_packs_do_not_include_counting_or_arithmetic_questions` |
| **J1.4** parse Choice / Score / Noul | J3 | `…::test_parse_choice_score_and_noul_from_recorded_unit_body` |
| **J1.4** bucket boundaries (D3) | J3 | `test_policy.py::test_bucket_confidence_at_every_band_boundary` |
| **J1.4** ordering | J3 | `…::test_order_units_by_choice_then_confidence_then_severity` |
| **J1.4** no skip / lower path (D7) | J3 | `…::test_high_confidence_clean_does_not_skip_reviewer` |
| **J1.4** steering ratchet (D5) | J3 | `test_ratchet_security.py::test_steering_payload_cannot_move_untrusted_verdict_downward` |
| **J1.4** untrusted cannot conclude clean | J3 | `…::test_untrusted_clean_cannot_be_concluded_without_prior` |
| **J1.5** shadow via existing recorder (D6) | J3 | `test_shadow.py::test_jev_prediction_is_a_shadow_jsonl_row` |
| **J1.5** disagreement groups | J3 | `…::test_disagreement_report_groups_by_lane_and_rule` |
| **J1.5** gate stays shadow | J3 | `test_settings.py::test_jev_gate_defaults_to_shadow` |
| **J1.6** `JevJudgePin` (D11) | J4 | `test_judge.py::test_jev_judge_pin_records_pinned_model` |
| **J1.6** unsupported quote | J4 | `…::test_evidence_pack_over_unsupported_quote` |
| **J1.6** blocker with no findings row | J4 | `…::test_claim_pack_over_blocker_summary_with_no_findings_row` |
| **J1.6** beside verifier | J4 | `…::test_judge_runs_beside_verifier_not_instead` |
| **J1.7** deterministic split (D12) | J4 | `test_claims.py::test_extract_claims_is_deterministic` |
| **J1.7** fences / tables / findings table | J4 | `…::test_fenced_code_is_held_out`, `test_markdown_tables_are_held_out`, `test_findings_table_is_held_out` |
| **J1.8** live catalog (G13) | J5 | `test_lens.py::test_lens_pack_is_derived_from_live_catalog_not_a_copy` |
| **J1.8** trigger fallback | J5 | `…::test_disabled_or_low_confidence_falls_back_to_trigger_matching` |
| **J1.8** withdrawn re-raise (G14) | J5 | `test_align.py::test_withdrawn_reraise_is_detected` |
| **J1.8** escalate-only dedupe (N5) | J5 | `…::test_semantic_dedupe_is_escalate_only_when_weaker_arrives_first` |
| **J1.9** ≥3 scenarios / pack (D15) | J1 (green) | `test_eval_corpus.py::test_corpus_has_at_least_three_scenarios_per_pack` |
| **J1.9** shipped-defect citations | J1 (green) | `…::test_every_corpus_row_traces_to_a_shipped_defect` |
| **J1.9** threshold without corpus row | J3 | `…::test_threshold_without_corpus_row_must_not_merge` |
| **D3** confidence stays ordinal | J1 (green) | `test_finding_source.py::test_finding_confidence_stays_three_value_ordinal` |
| **D3** `FindingSource` += `classifier` | J3 | `…::test_finding_source_gains_exactly_classifier` |
| **D3** float confidence still rejected | J1 (green) | `…::test_classifier_source_still_rejects_float_confidence` |
| **D14** no live marks / no secrets | J1 (green) | `test_no_live_calls.py` |

## Deliverable symbols

| Symbol | Module (planned) | Test anchor |
| --- | --- | --- |
| `PINNED_MODEL` | `jev/__init__.py`, `jev/client.py` | `test_client.py` |
| `AsyncJevClient` | `jev/client.py` | `test_client.py`, `test_cost.py`, `test_tracing.py` |
| `RecordedTransport` / `FlakyRecordedTransport` | `jev/client.py` | `test_client.py` |
| `TypeSafeAPIError` / `map_typesafe_error` | `jev/client.py` | `test_client.py` |
| `JevCallResult` / `JevError` | `jev/types.py` | `test_client.py`, `test_types.py` |
| `PRICE_TABLE` / `compute_cost` / `TokenBudget` | `jev/cost.py` | `test_cost.py` |
| `JevSettings` | `config/settings.py` | `test_settings.py`, `test_client.py` |
| `GatesSettings.jev` | `config/settings.py` | `test_settings.py`, `test_policy.py` |
| `segment_hunks` / `unit_id` / `unit_cache_key` / `residual_units` | `jev/segment.py` | `test_segment.py` |
| `unit_pack` / `evidence_pack` / `claim_pack` / `align_pack` / `lens_pack` / `get_pack` | `jev/questions.py` | `test_questions.py`, `test_lens.py` |
| `select_lenses` / `select_lenses_or_fallback` | `jev/questions.py` | `test_lens.py` |
| `bucket_confidence` / `order_units` / `predict_jev_action` / `apply_ratchet` | `jev/policy.py` | `test_policy.py`, `test_ratchet_security.py` |
| `unit_battery` / `dispatch_residual_units` | `jev/policy.py` | `test_dispatch.py` |
| `record_jev_prediction` / `iter_thresholds` | `jev/policy.py` | `test_shadow.py`, `test_eval_corpus.py`, `test_dispatch.py` |
| `detect_withdrawn_reraise` / `semantic_dedupe_pair` | `jev/policy.py` | `test_align.py` |
| `JevJudgePin` / `judge_finding_evidence` / `judge_prose_claims` / `run_parallel_judge` | `jev/judge.py` | `test_judge.py` |
| `jev-evidence-unsupported` / `jev-claim-unbacked-blocker` / `jev-claim-verdict-mismatch` | `jev/judge.py` | `test_judge.py` |
| `extract_claims` | `jev/claims.py` | `test_claims.py` |
| `FindingSource` + `classifier` | `review_taxonomy.py` | `test_finding_source.py` |

## Eval corpus

`tests/jev/corpus/jev-*.json` — three or more rows per pack, each citing a
defect this repo shipped:

| Pack | Rows |
| --- | --- |
| `unit/v1` | privilege-drop HOME; MCP config as root; auth-stem/`author` (`2f39b221`) |
| `evidence/v1` | plan 21 F1/F4 unread pointer; F5 discovery-as-delivery; D6 rule 1 quote mismatch |
| `claim/v1` | D6 rule 3 authz summary; 🚨 heading without a row; D6 rule 4 verdict without a blocker row |
| `align/v1` | audit r2 N5 / #711; withdrawn re-raise (D6 rule 2 / skill e4); auth/`author` paraphrase |
| `lens/v1` | privilege-drop-ordering vs security; data-integrity write-before-confirm; copy-vs-code help string |

## Escalation notes

- Skip reasons are the tokens `disabled`, `credential_absent`, and `kill_switch`
  on `JevCallResult.reason` — not English sentences.
- `JevError.code` is the message contract (`invalid_state`, `invalid_diff`,
  `invalid_confidence`, `invalid_body`, `invalid_response`).
- `apply_ratchet` must not be the identity function: the steering test fails if
  the untrusted verdict can move to `clean` / `Trivial`.
- `semantic_dedupe_pair` must not keep the first member when it is weaker (N5).
- `lens_pack()` must read `LENS_DEFINITIONS` at runtime (plan 21 D9).
- Thresholds are unset until J3; `iter_thresholds()` must name corpus ids.
- Jev must not score this corpus (D15 / out of scope).

## J6-wire — verifier findings (2026-09-17)

J6 (`wave-verifier`) found the library green and the review path unwired.
These tests pin the missing apply sites. They are ordinary assertions (no
xfail). Library-local rule-id guards may already pass; review-path and
skip/dispatch wiring stay RED until the executor lands J6-wire.

| Finding | Contract | Test(s) |
| --- | --- | --- |
| **F-WIRE-REVIEW** | `mergecraft review` / `run_offline_diff_review` constructs `AsyncJevClient` when `jev.enabled: true`. No `TYPESAFE_API_KEY` records `credential_absent` (log line or structured result field) and does not fail. `enabled: false` constructs nothing and does not require a skip (D4, D14). | `test_review_wire.py::test_enabled_review_without_credential_constructs_client_and_records_skip`, `…::test_disabled_review_does_not_construct_client_or_require_a_skip`, `…::test_cli_review_enabled_without_credential_records_skip_and_exits_zero` |
| **F-SKIP-RAISES** | `unit_battery` / `judge_finding_evidence` / `judge_prose_claims` / `select_lenses` must not raise `JevError` when the client returns a skip. Skip stays a skip (D4). Reintroducing raise-on-skip fails these tests. | `test_dispatch.py::test_unit_battery_skip_does_not_raise_jev_error`, `test_dispatch.py::test_dispatch_residual_units_skip_does_not_fail_the_run`, `test_judge.py::test_judge_finding_evidence_skip_does_not_raise`, `test_judge.py::test_judge_prose_claims_skip_does_not_raise`, `test_lens.py::test_select_lenses_skip_does_not_raise` |
| **F-UNBACKED-DISPATCH** | Direct behavioural tests for `unit_battery` and `dispatch_residual_units`. Analyzer-flagged hunks are not re-asked; residual hunks are; skip does not fail the run. | `test_dispatch.py::test_unit_battery_parses_recorded_unit_pack`, `…::test_dispatch_residual_units_asks_residual_not_analyzer_flagged`, `…::test_dispatch_residual_units_skip_does_not_fail_the_run` |
| **F-UNBACKED-RULE-IDS** | Attestation rule ids fail if the emit-`if` blocks are deleted. Attestations are `scope="run"` and never blocking (D6). Plan 21 D6 rule 4 (exactly one terminal verdict) fails when the body names two verdicts. | `test_judge.py::test_unsupported_evidence_emits_jev_evidence_unsupported`, `…::test_unbacked_blocker_emits_jev_claim_unbacked_blocker`, `…::test_verdict_mismatch_emits_jev_claim_verdict_mismatch`, `…::test_two_terminal_verdicts_violate_exactly_one_verdict_rule` |
| **F-GATE-DISCARD** | `GatesSettings.jev` is applied (not read-and-discarded). Default `shadow`; `enforced` stays false even when the setting is `enforce` (D6). | `test_policy.py::test_predict_jev_action_honors_shadow_gate_mode`, `…::test_predict_jev_action_stays_unenforced_when_gate_set_to_enforce` |
| **F-PACKS-DEAD** | `JevSettings.packs` has an apply site. A disabled pack is not dispatched. | `test_client.py::test_disabled_pack_is_a_recorded_skip_not_a_dispatch`, `test_packs.py::test_client_does_not_dispatch_a_disabled_pack`, `…::test_unit_battery_skips_disabled_unit_pack`, `…::test_judge_skips_disabled_evidence_pack`, `…::test_select_lenses_skips_disabled_lens_pack` |
| **F-UNIT-THRESHOLDS** | `unit/v1.certain` / `unit/v1.likely` are read by bucketing / `iter_thresholds`. Changing the setting changes the bucket boundary. | `test_policy.py::test_bucket_confidence_reads_configured_unit_thresholds`, `…::test_iter_thresholds_unit_floors_follow_settings` |
| **F-DISPATCH-NO-SHADOW** | `dispatch_residual_units` calls `record_jev_prediction`. Removing that call fails the test. | `test_dispatch.py::test_dispatch_residual_units_calls_record_jev_prediction` |

Skip observability is `JevCallResult.reason` / `skipped`, `OfflineReviewResult.jev_skip_reason` (if added), or the existing client log `jev skip reason=credential_absent` — not a substring in a question dict. CI still makes zero live TypeSafe calls (D14).
