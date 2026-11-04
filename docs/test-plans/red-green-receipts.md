# Test plan — fail-then-pass receipts for fix pull requests

Part 5 of #1056. A pull request classified as a fix (conventional `fix` title,
or a label in `review.fixLabels`, default `bug` / `fix`) must carry a declared
fail-then-pass receipt: a JSON artifact the consumer's own CI uploads, read by
mergeCraft only from a **successful** workflow run on the head SHA and bound to
the run's exact base and head SHAs. mergeCraft never runs the tests. The
receipt's status becomes one `fix.*` lane reason and a `fix_proof` checklist
gate; a fix without a `proven` receipt is at least `medium` and never
`eligible`. No packet section is added: the verdict rides in `reasons`.

## Test strategy

New names are imported inside each test (`_rg()`, `_ingest()`, `_api()`) so
the suite collects on the anchor and every test fails on its own rather than as
a collection error. Each test drives a public seam:

- the pure parser module `mergecraft.ci.red_green`;
- the ingest collector `mergecraft.ci.sarif_ingest.collect_ci_red_green_evidence`
  against a fake `GitHubClient` subclass (the coverage-ingest pattern), and the
  action-side `ingest_ci_sarif_for_head_sha` end to end;
- the classifier `classify_blast_radius` and the run-diff classifier
  `classify_run_blast_radius(diff_text, *, fix_proof=...)`;
- `build_run_packet` on a real `ToolContext` plus
  `render_deterministic_review_block` for the run record;
- the settings models and `load_repo_settings`;
- the docs, REVIEW-CHECKS.md and CHANGELOG.md text.

`GATE_ORDER` is asserted only as "the ten part-2 gates first, then
`fix_proof` once": another lane appends its own gate concurrently.

The oversized receipt is booby-trapped: a `bytes` subclass whose `decode`
fails the test, padded so the document would be a valid `proven` receipt if it
were parsed. Refusing it as `oversized` proves the size check comes before any
decode. The no-execution test patches every `subprocess`, `os` and `asyncio`
process entry point to fail and record, and feeds an artifact that also
contains `run-tests.sh`, `conftest.py` and a `Makefile`, with shell-looking test
ids; the receipt must still be read as `proven`.

## Seams the implementation must provide

| Seam | Shape |
| --- | --- |
| `mergecraft.ci.red_green` | `TestResult`, `RedGreenTest(id, base, head)`, `RedGreenReceipt(base_sha, head_sha, tests: tuple)`, `RedGreenVerdict`, `RedGreenReceiptError(kind=...)` with `.kind`, `parse_red_green_receipt(raw, *, max_bytes=1_000_000)`, `red_green_verdict(receipt)`, `receipt_matches(receipt, *, base_sha, head_sha)`, `is_fix_pull_request(title, labels, *, fix_labels)` (labels are names), `RedGreenEvidence(status, test_count, artifact, run_url, detail)` (frozen) |
| `mergecraft.ci.sarif_ingest` | `collect_ci_red_green_evidence(ctx, *, client, runs, artifacts, base_sha, head_sha) -> RedGreenEvidence`; `ingest_ci_sarif_for_head_sha` records it on `ToolState.red_green` when names are declared, taking the base SHA from `ctx.gh_event["pull_request"]["base"]["sha"]` |
| `ToolContext` | `ci_red_green_artifacts: list[str]` keyword, filled from `settings.ci_evidence.red_green_artifacts` like the other `ciEvidence` names |
| `ToolState` | `red_green` field, `None` by default |
| Settings | `CiEvidenceSettings.red_green_artifacts` (alias `redGreenArtifacts`, default `[]`); `ReviewSettings.fix_labels` (alias `fixLabels`, default `["bug", "fix"]`) |
| Classifier | `FixProofSignal` TypedDict (`required`, `status`); `ChangeSet.fix_proof`; six `fix.*` catalogue codes; `fix_proof` appended to `GATE_ORDER` |
| Run packet | `classify_run_blast_radius(diff_text, *, fix_proof=None)`; `build_run_packet` builds the signal from `ToolState.red_green`, the PR title (`ctx.payload.event.title`, also set on `gh_event.pull_request.title` in the tests) and `gh_event.pull_request.labels[*].name`, with `fix_labels` from `ctx.repo_settings_snapshot` (defaults when there is none) |

A run is successful when `status == "completed"` and `conclusion == "success"`
on the listing row; the run URL is the row's `html_url`. The receipt is a JSON
member of the artifact zip (`red-green.json` in the tests).

## Coverage map

| Contract | What it proves | Tests |
| --- | --- | --- |
| Parse a valid receipt | Typed, frozen models; `tests` is a tuple in input order; `str` and `bytes` give the same receipt; every `TestResult` literal; empty list; unicode ids | `tests/ci/test_red_green_receipt.py::test_a_valid_receipt_parses_into_typed_models`, `::test_bytes_and_str_inputs_parse_to_the_same_receipt`, `::test_the_tests_keep_their_order`, `::test_every_test_result_literal_is_accepted`, `::test_an_empty_test_list_parses`, `::test_a_unicode_test_id_is_preserved`, `::test_the_receipt_and_its_tests_are_frozen` |
| 1 MB cap | Exactly 1 000 000 bytes parses; 1 000 001 bytes is `oversized` and never decoded; an oversized `str` is refused; the cap counts UTF-8 bytes; `max_bytes` holds on both sides of the boundary | `test_red_green_receipt.py::test_the_default_cap_is_one_megabyte_and_a_receipt_at_the_cap_parses`, `::test_a_receipt_one_byte_over_the_cap_is_oversized_and_never_decoded`, `::test_an_oversized_str_receipt_is_refused`, `::test_the_cap_counts_utf8_bytes_not_characters`, `::test_max_bytes_is_honoured_on_both_sides_of_the_boundary` |
| Count and id bounds | 2 000 tests parse, 2 001 are `invalid`; a 500-character id parses, 501 is `invalid` | `test_red_green_receipt.py::test_two_thousand_tests_parse`, `::test_two_thousand_and_one_tests_are_invalid`, `::test_a_test_id_of_five_hundred_characters_parses`, `::test_a_test_id_of_five_hundred_and_one_characters_is_invalid` |
| Invalid documents | Non-JSON, truncated JSON, non-object top level, empty input, invalid UTF-8, wrong or foreign schema id, a missing required key, an unknown top-level or per-test key, wrong container types, an unknown result literal, non-string SHA or id: each raises `RedGreenReceiptError` with `kind == "invalid"` and a message | `test_red_green_receipt.py::test_an_invalid_receipt_raises_the_invalid_kind`, `::test_the_error_carries_its_kind` |
| Verdict | `proven` needs at least one `failed`/`error` on base and every listed test `passed` on head; a still-failing, erroring, skipped or regressed head test, a never-red receipt and an all-skipped receipt are `not-proven`; empty is `no-tests` | `test_red_green_receipt.py::test_the_verdict_table`, `::test_a_receipt_built_in_code_gets_the_same_verdict` |
| SHA binding | Full-length, case-insensitive hex compare; a short SHA on either side, a swap, one differing character, empty strings and non-hex strings never match; keyword-only | `test_red_green_receipt.py::test_receipt_matches_compares_full_length_hex_case_insensitively`, `::test_receipt_matches_takes_the_shas_by_keyword_only` |
| Fix detection | `fix:`, `fix(scope):`, `fix!:`, `fix(scope)!:` are fixes; `fixture:`, `prefix:`, `fixes:`, `feat: fix …`, `chore(fix):`, a `fix:` later in the title and an empty title are not; any configured label, case-insensitive on both sides, exact (not prefix) match; a configured list replaces the default; keyword-only `fix_labels` | `test_red_green_receipt.py::test_a_conventional_fix_title_makes_a_fix_pull_request`, `::test_a_fix_label_makes_a_fix_pull_request`, `::test_a_fix_title_needs_no_label`, `::test_a_label_alone_marks_a_fix_whatever_the_title_says`, `::test_fix_labels_is_keyword_only` |
| Pure module | `ci/red_green.py` imports no subprocess, network, async or SCM client | `test_red_green_receipt.py::test_the_receipt_module_does_no_io` |
| Evidence record | `ToolState.red_green` starts `None`; `RedGreenEvidence` is frozen, carries the five fields and accepts every status | `tests/ci/test_red_green_ingest.py::test_tool_state_starts_with_no_red_green_evidence`, `::test_red_green_evidence_is_frozen_and_carries_the_contract_fields`, `::test_red_green_evidence_accepts_every_status_in_the_vocabulary` |
| Ingest outcomes | A matching receipt from a successful run is `proven` with count, artifact and run URL; `not-proven`; `no-tests`; other, swapped or short SHAs are `mismatch`; an uppercase receipt matches; non-JSON, wrong schema and unknown key are `invalid`; oversized is `invalid` and the detail says so | `test_red_green_ingest.py::test_a_proven_receipt_from_a_successful_run_records_proven`, `::test_a_receipt_with_a_test_still_failing_on_head_records_not_proven`, `::test_an_empty_receipt_records_no_tests`, `::test_a_receipt_for_other_shas_records_mismatch`, `::test_an_uppercase_receipt_for_the_right_shas_is_proven`, `::test_an_unparseable_receipt_records_invalid`, `::test_an_oversized_receipt_records_invalid_and_says_oversized` |
| Only a successful run counts | Failure, cancelled, timed-out, neutral, in-progress and queued runs are never downloaded (`no-receipt`); beside a failed run, only the successful run's receipt is read; a run on another head SHA is never read | `test_red_green_ingest.py::test_a_receipt_from_a_run_that_did_not_succeed_is_never_read`, `::test_only_the_successful_runs_receipt_is_read`, `::test_a_run_for_another_head_sha_is_never_read` |
| Missing receipt, never raises | A failed download, a run without the named artifact, no runs at all and a corrupt zip each record a status instead of raising | `test_red_green_ingest.py::test_a_failed_download_records_no_receipt`, `::test_a_successful_run_without_the_named_artifact_records_no_receipt`, `::test_no_runs_on_the_head_records_no_receipt`, `::test_a_bad_zip_records_no_receipt_or_invalid_and_never_raises` |
| Undeclared | No names (or only blank names) records `not-declared` with no API call | `test_red_green_ingest.py::test_undeclared_artifacts_record_not_declared_and_make_no_call`, `::test_blank_artifact_names_count_as_undeclared` |
| Nothing is executed | Every process entry point is trapped; a hostile artifact is read as `proven` with no spawn | `test_red_green_ingest.py::test_ingest_never_runs_anything_from_the_artifact` |
| Action-side ingest | `ingest_ci_sarif_for_head_sha` records the evidence on `ToolState.red_green`, binds it to the event's base SHA, records `no-receipt` for a failed run and survives a failed download | `test_red_green_ingest.py::test_head_sha_ingest_records_the_receipt_on_tool_state`, `::test_head_sha_ingest_binds_the_receipt_to_the_bound_base_sha`, `::test_head_sha_ingest_records_no_receipt_for_a_failed_run`, `::test_head_sha_ingest_never_raises_when_the_download_fails` |
| Settings | Defaults (`[]`, `["bug", "fix"]`), YAML declaration, an empty `fixLabels`, alias and field name, alias round trip, a string or a non-string label refused at the alias with the type error, the forbid-extra posture kept | `tests/ci/test_red_green_settings.py` |
| Catalogue and gate | Six `fix.*` codes with their lanes; part-2 lanes unchanged; `fix_proof` once after the part-2 gates; `FixProofSignal` keys and `ChangeSet.fix_proof` | `tests/classify/test_blast_radius_fix_proof.py::test_each_fix_code_is_in_the_catalogue_with_its_default_lane`, `::test_the_part2_codes_keep_their_lanes`, `::test_fix_proof_is_appended_after_the_part2_gates_once`, `::test_the_signal_types_carry_the_contract_keys` |
| Proven / not required | A proven fix is `low`, `eligible`, every gate `true`; a non-fix is `fix.not-required` whatever the status | `test_blast_radius_fix_proof.py::test_a_fix_with_a_proven_receipt_passes_the_gate_and_stays_low`, `::test_a_non_fix_pull_request_is_not_required_and_passes_the_gate`, `::test_a_non_fix_pull_request_is_not_required_whatever_the_status` |
| Unproven fixes escalate | `not-proven`, `no-receipt`, `invalid`, `mismatch`, `not-declared` → `medium`, `assisted`, its own code, gate `false`; `no-tests` → `medium` with a non-passing `fix.*` code; `not-declared` names `redGreenArtifacts` and reads differently from `no-receipt`; no unproven status is ever `eligible` | `test_blast_radius_fix_proof.py::test_a_fix_without_a_proven_receipt_is_medium_with_its_code`, `::test_a_fix_whose_receipt_lists_no_tests_never_passes`, `::test_an_undeclared_receipt_on_a_fix_names_the_setting`, `::test_a_missing_receipt_message_differs_from_an_undeclared_one`, `::test_a_fix_pr_is_never_eligible_without_a_proven_receipt` |
| High wins, floors hold | A proven fix beside a migration stays `high`; an unproven one too; a proven fix cannot lower `source.changed` or a missing input | `test_blast_radius_fix_proof.py::test_a_proven_fix_beside_a_high_reason_stays_high`, `::test_an_unproven_fix_beside_a_high_reason_stays_high`, `::test_a_proven_fix_cannot_lower_a_medium_source_change`, `::test_a_proven_fix_with_missing_inputs_stays_medium` |
| Part-2 invariants | `lane == max(reasons)`, exactly one `fix.*` reason, `eligible` ⇔ every gate `true` ⇔ `low`, codes in the catalogue, checklist in `GATE_ORDER`, both sides of the equivalence exercised | `test_blast_radius_fix_proof.py::test_the_lane_is_the_max_over_reasons_with_a_fix_signal`, `::test_eligible_iff_every_gate_passed_iff_low_with_a_fix_signal`, `::test_every_code_with_a_fix_signal_is_in_the_catalogue`, `::test_the_invariant_table_has_both_eligible_and_non_eligible_rows`, `::test_the_rendered_reason_names_the_fix_code` |
| No signal | Without `fix_proof` the part-2 classification is unchanged (`baseline.clean`, `low`, `eligible`) | `test_blast_radius_fix_proof.py::test_no_signal_leaves_the_part2_classification_unchanged`, `::test_the_run_diff_classifier_without_a_signal_adds_no_fix_reason` |
| Run-diff classifier | The signal passes through; it is keyword-only | `test_blast_radius_fix_proof.py::test_the_run_diff_classifier_passes_the_signal_through`, `::test_the_run_diff_classifier_takes_the_signal_by_keyword_only` |
| Run packet | Title + `proven` evidence → `fix.proven`; title without evidence → `fix.no-receipt`; each recorded status → its code; a feature → `fix.not-required`; a default label; configured labels replace the defaults; a proven receipt on a non-fix stays `fix.not-required`; no new packet key | `test_blast_radius_fix_proof.py::test_a_fix_titled_run_*`, `::test_a_feature_run_is_not_required`, `::test_a_default_fix_label_makes_the_run_a_fix`, `::test_the_configured_fix_labels_replace_the_defaults`, `::test_a_proven_receipt_on_a_non_fix_run_is_still_not_required`, `::test_the_fix_proof_adds_no_packet_section` |
| Run record | One record line names the `fix.*` code | `test_blast_radius_fix_proof.py::test_the_run_record_names_the_fix_code` |
| Docs | `docs/blast-radius.md` *Fix proof* section; `docs/red-green-receipts.md` has the schema id, the 1 MB cap, the keys and no `${{`; REVIEW-CHECKS.md says the tests are never run; CHANGELOG `### Added` names `redGreenArtifacts`. The *Lane reasons* rows are enforced by the existing catalogue test | `test_blast_radius_fix_proof.py::test_the_blast_radius_doc_has_a_fix_proof_section`, `::test_the_receipt_doc_documents_the_format_and_the_cap`, `::test_review_checks_says_receipts_never_run_tests`, `::test_the_changelog_adds_the_receipts_under_unreleased`; `tests/classify/test_lane_reason_catalogue.py` |

## Matrix

| Layer | Happy path | Edge cases | Error handling |
| --- | --- | --- | --- |
| Unit | valid receipt; `proven` verdict; exact SHA match; `fix:` titles and labels; proven fix → `low` | cap boundary, UTF-8 bytes, 2 000 / 500 bounds, ordering, unicode, case, short SHAs, `fixture:` / `prefix:` | every `invalid` shape; `oversized` never decoded; unproven statuses escalate |
| Integration | collector → `RedGreenEvidence`; `ingest_ci_sarif_for_head_sha` → `ToolState.red_green`; settings YAML | failed run beside a successful one; another head SHA; blank names; uppercase receipt | failed download, missing artifact, bad zip, mismatch; no subprocess |
| Functional | `build_run_packet` → reasons and gate; run record line | configured labels replace defaults; proven receipt on a non-fix | fix without evidence → `fix.no-receipt`, `medium` |

## Not pinned (left to the implementation)

- The `fix.*` code for a fix whose receipt lists no tests (`no-tests`): it must
  be one non-passing `fix.*` code at `medium`.
- Error message wording; only `kind` and a non-empty message are asserted.
- Whether the run record shows the status on the *Blast radius* line or its own
  line: one line must carry the `fix.*` code.
- Which zip member holds the receipt, beyond a JSON member named
  `red-green.json` being read.
- Several successful runs that each upload a receipt.
- `Fix:` (capitalised type) and leading whitespace in a title.

## Open question for the orchestrator

The plan says the `fix_proof` gate is `null` when no signal was supplied. The
part-2 tests already on `main` require a complete low change classified
without any `fix_proof` to pass every gate and stay `eligible`
(`test_blast_radius_reasons.py::test_a_low_code_alone_passes_every_gate`,
`::test_a_complete_change_measures_every_gate`,
`::test_the_run_record_line_has_no_suffix_when_every_gate_is_measured`), and
`eligible` ⇔ every gate `true`. Both cannot hold. This suite keeps the part-2
tests satisfiable: `test_no_signal_leaves_the_part2_classification_unchanged`
pins the unchanged classification and does not pin the gate value, so with the
part-2 tests the gate reads `true` when no signal is supplied. If the
orchestrator chooses `null` instead, the part-2 tests above and this one need
amending together (the same question applies to the concurrent `scope` gate).

## Amendments

None yet.
