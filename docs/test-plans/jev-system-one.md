# Jev / System One — test plan

Wave plan: `.ignorelocal/waves/23-jev-system-one-wave-plan.md`
Worktree: `mc-jev` @ `wave/jev-system-one`
Authoring wave: **J1** (`test-creator`). Implementation: **J2–J5**. Final: **J6**.

Recorded TypeSafe envelopes live under `tests/jev/fixtures/transport/`. CI makes
zero live TypeSafe calls (D14). J0 live smoke is `skipped: no live credential`.

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
| `GatesSettings.jev` | `config/settings.py` | `test_settings.py` |
| `segment_hunks` / `unit_id` / `unit_cache_key` / `residual_units` | `jev/segment.py` | `test_segment.py` |
| `unit_pack` / `evidence_pack` / `claim_pack` / `align_pack` / `lens_pack` / `get_pack` | `jev/questions.py` | `test_questions.py`, `test_lens.py` |
| `select_lenses` / `select_lenses_or_fallback` | `jev/questions.py` | `test_lens.py` |
| `bucket_confidence` / `order_units` / `predict_jev_action` / `apply_ratchet` | `jev/policy.py` | `test_policy.py`, `test_ratchet_security.py` |
| `record_jev_prediction` / `iter_thresholds` | `jev/policy.py` | `test_shadow.py`, `test_eval_corpus.py` |
| `detect_withdrawn_reraise` / `semantic_dedupe_pair` | `jev/policy.py` | `test_align.py` |
| `JevJudgePin` / `judge_finding_evidence` / `judge_prose_claims` / `run_parallel_judge` | `jev/judge.py` | `test_judge.py` |
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
