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
- the base-side resolvers `resolve_fix_labels` and `resolve_red_green_declaration`
  against a contents-API fake, and the run-start writers through the real
  `main._run_review_after_analyze` with the I/O phases stubbed;
- the classifier `classify_blast_radius`, fed by the shared helper
  `evidence/run_packet.py::fix_proof_signal_for_state`;
- `build_run_packet` on a real `ToolContext` plus
  `render_deterministic_review_block` for the run record, and the verification
  tool's `_run_lane`, which must agree with the packet. `classify_run_blast_radius`
  is exercised only through these two callers, because its keyword-only
  signals (`scope`, `fix_proof`) are required and another lane adds `scope`;
- the approval-gate predicates `_is_low_risk_passing`, `_is_clean_pass` and
  `select_rule_id` in `mergecraft.agents.gates`;
- the settings models and `load_repo_settings`;
- the docs, REVIEW-CHECKS.md and CHANGELOG.md text.

`GATE_ORDER` is asserted only as "the ten part-2 gates first, then
`fix_proof` once": another lane appends its own gate concurrently. No test
asserts the exact tail of `GATE_ORDER`. A checklist is compared with
`GATE_ORDER` as an ordered subsequence, because an unsupplied signal's gate is
omitted.

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
| `mergecraft.ci.sarif_ingest` | `collect_ci_red_green_evidence(ctx, *, client, runs, declaration, base_sha, head_sha) -> RedGreenEvidence`, where `declaration` is a `RedGreenReceiptSettings` or `None` (`not-declared`, no API call). A run counts only when it is `completed`/`success` on the head SHA, its `path` equals the declared `workflow`, and its `head_repository.full_name` is the reviewed repository (a fork is `no-receipt` naming the fork; a missing one is `no-receipt`). It also counts only when the unfiltered change set (review diff paths, including rename sources, plus `ToolState.ignored_review_paths` and `coverage.unreviewable_paths`) does not contain the workflow (otherwise `no-receipt` naming it). It fails closed with `no-receipt` and "could not be verified" when `coverage.diff_truncated` is set or the diff is missing or unreadable. The listing's `size_in_bytes` must be a non-negative int of at most 2 MiB (2 097 152) before download, else `no-receipt` and no download. The receipt member is read with `read(1_000_001)` at most. A forged run never shadows the real one. `ingest_ci_sarif_for_head_sha` reads `ToolState.red_green_declaration` and records the result on `ToolState.red_green` |
| `ToolState` (declaration) | `red_green_declaration: Optional[RedGreenReceiptSettings] = None`, resolved at run start before the action-side CI ingest |
| `ToolState` | `red_green` field, `None` by default |
| Settings | `CiEvidenceSettings.red_green: Optional[RedGreenReceiptSettings]` (alias `redGreen`, default `None`); `RedGreenReceiptSettings(artifact: str, workflow: str)`, both required, unknown keys refused, a workflow path that is absolute or has a `..` segment refused at `workflow`; `redGreenArtifacts` is an unknown key. `ReviewSettings.fix_labels` (alias `fixLabels`, default `["bug", "fix"]`) |
| Classifier | `FixProofSignal` TypedDict (`required`, `status`); `ChangeSet.fix_proof`; six `fix.*` catalogue codes; `fix_proof` appended to `GATE_ORDER`. No `fix_proof` key → the gate is omitted from `checklist` and no `fix.*` reason is emitted; a supplied signal always yields a boolean gate |
| Shared helper | `evidence/run_packet.py::fix_proof_signal_for_state(state, *, title, labels, fix_labels) -> FixProofSignal`; `labels` are label names; the status is `ToolState.red_green.status`, and `no-receipt` or `not-declared` when there is no evidence; `detail` carries `ToolState.red_green.detail`. `FixProofSignal` gains an optional `detail: str`, and the `fix.receipt.invalid`, `fix.no-receipt` and `fix.receipt.mismatch` messages include it |
| Run packet / verification | `classify_run_blast_radius(diff_text, *, scope, fix_proof)` with both keywords required; `build_run_packet` and `mcp/verification.py::_run_lane` both build the signal through the helper from `ToolState.red_green`, the PR title (`ctx.payload.event.title`, also set on `gh_event.pull_request.title` in the tests) and `gh_event.pull_request.labels[*].name`, with `fix_labels` from `ctx.repo_settings_snapshot` (defaults when there is none) |
| Base-side fix labels | `review_policy/fix_labels.py::resolve_fix_labels(scm, owner, repo, *, event, run_start_review, operator_owned) -> tuple[str, ...]`, mirroring `resolve_review_ignore`: an operator-owned run (`pull_request_target`) uses the run-start `review.fixLabels` without a read; otherwise it reads the base commit's `.mergecraft/config.yaml` through the contents API at `pull_request.base.sha`. A base without the key, an unreadable base or an unknown base SHA gives the defaults, never the head's list. Run start stores the result on `ToolState.fix_labels` (`None` until resolved). `fix_proof_signal_for_context` uses `ToolState.fix_labels` when set, else the snapshot's list only when `snapshot.operator_owned`, else the defaults |
| Base-side receipt declaration | `review_policy/red_green.py::resolve_red_green_declaration(scm, owner, repo, *, event, run_start_ci_evidence, operator_owned) -> Optional[RedGreenReceiptSettings]`, mirroring `resolve_fix_labels`: an operator-owned run uses the run-start block without a read; any other pull request run reads the base commit's config at `pull_request.base.sha`. A base without the block, a 404, a failed read, an invalid block (`..`, a missing key, unparseable YAML) or an unknown base SHA gives `None`, never the head's block. `main._run_review_after_analyze` resolves it onto `ToolState.red_green_declaration` before `ingest_ci_sarif_from_action_env`, and records `not-declared` on `ToolState.red_green` when it is `None` |
| Approval gate | `_is_low_risk_passing` and `clean_pass` refuse a packet whose non-empty checklist lacks any gate in `GATE_ORDER`, on top of the part-2 rules |

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
| Fix detection | `fix:`, `fix(scope):`, `fix!:`, `fix(scope)!:` are fixes, case-insensitive in the type (`Fix:`, `FIX(ci):`) and after leading whitespace is stripped; `fixture:`, `prefix:`, `fixes:`, `feat: fix …`, `chore(fix):`, a `fix:` later in the title and an empty title are not; any configured label, case-insensitive on both sides, exact (not prefix) match; a configured list replaces the default; keyword-only `fix_labels` | `test_red_green_receipt.py::test_a_conventional_fix_title_makes_a_fix_pull_request`, `::test_a_fix_label_makes_a_fix_pull_request`, `::test_a_fix_title_needs_no_label`, `::test_a_label_alone_marks_a_fix_whatever_the_title_says`, `::test_fix_labels_is_keyword_only` |
| Pure module | `ci/red_green.py` imports no subprocess, network, async or SCM client | `test_red_green_receipt.py::test_the_receipt_module_does_no_io` |
| Evidence record | `ToolState.red_green` and `ToolState.red_green_declaration` start `None`; `RedGreenEvidence` is frozen, carries the five fields and accepts every status | `tests/ci/test_red_green_ingest.py::test_tool_state_starts_with_no_red_green_evidence_or_declaration`, `::test_red_green_evidence_is_frozen_and_carries_the_contract_fields`, `::test_red_green_evidence_accepts_every_status_in_the_vocabulary` |
| Ingest outcomes | A matching receipt from the declared same-repository run is `proven` with count, artifact and run URL; `not-proven`; `no-tests`; other, swapped or short SHAs are `mismatch`; an uppercase receipt matches; non-JSON, wrong schema and unknown key are `invalid`; oversized is `invalid` and the detail says `oversized` exactly once | `test_red_green_ingest.py::test_a_proven_receipt_from_the_declared_workflow_records_proven`, `::test_a_receipt_with_a_test_still_failing_on_head_records_not_proven`, `::test_an_empty_receipt_records_no_tests`, `::test_a_receipt_for_other_shas_records_mismatch`, `::test_an_uppercase_receipt_for_the_right_shas_is_proven`, `::test_an_unparseable_receipt_records_invalid`, `::test_an_oversized_receipt_says_oversized_once` |
| Only a successful run counts | Failure, cancelled, timed-out, neutral, in-progress and queued runs are never downloaded (`no-receipt`); beside a failed run, only the successful run's receipt is read; a run on another head SHA is never read | `test_red_green_ingest.py::test_a_receipt_from_a_run_that_did_not_succeed_is_never_read`, `::test_only_the_successful_runs_receipt_is_read`, `::test_a_run_for_another_head_sha_is_never_read` |
| Missing receipt, never raises | A failed download, a declared run without the declared artifact, no runs at all and a corrupt zip each record a status instead of raising | `test_red_green_ingest.py::test_a_failed_download_records_no_receipt`, `::test_a_declared_run_without_the_declared_artifact_records_no_receipt`, `::test_no_runs_on_the_head_records_no_receipt`, `::test_a_bad_zip_records_no_receipt_or_invalid_and_never_raises` |
| Undeclared | No declaration records `not-declared` with no API call | `test_red_green_ingest.py::test_no_declaration_records_not_declared_and_makes_no_call` |
| Nothing is executed | Every process entry point is trapped; a hostile artifact is read as `proven` with no spawn | `test_red_green_ingest.py::test_ingest_never_runs_anything_from_the_artifact` |
| Action-side ingest | `ingest_ci_sarif_for_head_sha` reads `ToolState.red_green_declaration`, records the evidence on `ToolState.red_green`, binds it to the event's base SHA, records `no-receipt` for a failed run and survives a failed download | `test_red_green_ingest.py::test_head_sha_ingest_reads_the_declaration_from_tool_state`, `::test_head_sha_ingest_binds_the_receipt_to_the_bound_base_sha`, `::test_head_sha_ingest_records_no_receipt_for_a_failed_run`, `::test_head_sha_ingest_never_raises_when_the_download_fails` |
| Receipt provenance | A run of another workflow (PR-added, another workflow, no `path`) is never read. A fork run of the declared workflow is `no-receipt` and names the fork. A run without `head_repository` is never read. A forged run (fork-added workflow, fork with the declared path, same-repository other workflow) before or after the real run never shadows it, and only the real artifact is downloaded. The verifier's forgery, a fork PR adding its own workflow, goes end to end to `fix.no-receipt` at `medium`, never `low_risk_passing`; the declared run is the control | `test_red_green_ingest.py::test_a_run_of_another_workflow_is_never_read`, `::test_a_fork_run_of_the_declared_workflow_is_never_read_and_is_named`, `::test_a_run_without_a_head_repository_is_never_read`, `::test_a_forged_run_beside_the_real_one_does_not_shadow_it`, `::test_the_fork_pr_added_workflow_forgery_never_proves_a_fix`, `::test_the_real_declared_run_proves_the_same_fix` |
| Declared workflow unchanged | A visible edit, a rename away, an ignored-by-config edit or an unreviewable edit of the declared workflow is `no-receipt` naming it, with no download. A truncated, missing or unreadable diff fails closed ("could not be verified", no download). Editing another workflow still reads the receipt | `test_red_green_ingest.py::test_a_pr_that_changes_the_declared_workflow_gets_no_receipt`, `::test_an_unverifiable_change_set_fails_closed`, `::test_editing_another_workflow_still_reads_the_receipt` |
| Archive and member bounds | `size_in_bytes` one past 2 MiB, 50 MiB, missing, negative, a string or a bool → `no-receipt`, never downloaded; exactly 2 MiB is downloaded. A ~48 KB zip holding a 50 MB member is `invalid`/oversized with every `ZipExtFile.read` bounded by 1 000 001 bytes | `test_red_green_ingest.py::test_an_archive_too_large_or_of_unknown_size_is_never_downloaded`, `::test_an_archive_of_exactly_2_mib_is_downloaded`, `::test_a_small_zip_with_a_huge_member_is_read_only_to_the_cap` |
| Base-side declaration | An operator-owned run uses its run-start block with no read; a fork run reads the base at its SHA; a head-only block is ignored; a head that rewrites the base block is ignored; a 404, a failed read, a `..` workflow, a missing key or garbage YAML on the base declare nothing; an unknown base SHA declares nothing with no read | `tests/review_policy/test_red_green_declaration.py` |
| Run-start writers | Through `main._run_review_after_analyze` with a base-config SCM: the base `fixLabels: [regression]` is on `ToolState.fix_labels` by the triage gate (deleting `_resolve_run_fix_labels` fails it); the base `redGreen` block is on `ToolState.red_green_declaration` both at the action-side CI ingest and at triage; a head-only block is ignored and `ToolState.red_green` is `not-declared`; an operator-owned run uses its own block with no base read | `tests/ci/test_red_green_run_start.py` |
| Settings | Defaults (`redGreen` `None`, `["bug", "fix"]`), YAML declaration of both, an empty `fixLabels`, alias and field name, alias round trip, both receipt keys required (`missing` at `("redGreen", key)`), absolute or `..` workflow paths refused at `workflow`, repo-relative paths (including dots inside a name) accepted, unknown block keys refused, `redGreenArtifacts` now `extra_forbidden`, a non-string label refused | `tests/ci/test_red_green_settings.py` |
| Catalogue and gate | Six `fix.*` codes with their lanes; part-2 lanes unchanged; `fix_proof` once after the part-2 gates; `FixProofSignal` keys and `ChangeSet.fix_proof` | `tests/classify/test_blast_radius_fix_proof.py::test_each_fix_code_is_in_the_catalogue_with_its_default_lane`, `::test_the_part2_codes_keep_their_lanes`, `::test_fix_proof_is_appended_after_the_part2_gates_once`, `::test_the_signal_types_carry_the_contract_keys` |
| Proven / not required | A proven fix is `low`, `eligible`, every gate `true`; a non-fix is `fix.not-required` whatever the status | `test_blast_radius_fix_proof.py::test_a_fix_with_a_proven_receipt_passes_the_gate_and_stays_low`, `::test_a_non_fix_pull_request_is_not_required_and_passes_the_gate`, `::test_a_non_fix_pull_request_is_not_required_whatever_the_status` |
| Unproven fixes escalate | `not-proven` and `no-tests` → `fix.not-proven`; `no-receipt` and `not-declared` → `fix.no-receipt`; `invalid` → `fix.receipt.invalid`; `mismatch` → `fix.receipt.mismatch`; each `medium`, `assisted`, gate `false`; `not-declared` names `ciEvidence.redGreen` (never `redGreenArtifacts`) and reads differently from `no-receipt`; no unproven status is ever `eligible` | `test_blast_radius_fix_proof.py::test_a_fix_without_a_proven_receipt_is_medium_with_its_code`, `::test_an_undeclared_receipt_on_a_fix_names_the_setting`, `::test_a_missing_receipt_message_differs_from_an_undeclared_one`, `::test_a_fix_pr_is_never_eligible_without_a_proven_receipt` |
| High wins, floors hold | A proven fix beside a migration stays `high`; an unproven one too; a proven fix cannot lower `source.changed` or a missing input | `test_blast_radius_fix_proof.py::test_a_proven_fix_beside_a_high_reason_stays_high`, `::test_an_unproven_fix_beside_a_high_reason_stays_high`, `::test_a_proven_fix_cannot_lower_a_medium_source_change`, `::test_a_proven_fix_with_missing_inputs_stays_medium` |
| Part-2 invariants | `lane == max(reasons)`, exactly one `fix.*` reason, `eligible` ⇔ every listed gate `true` ⇔ `low`, codes in the catalogue, the checklist an ordered subsequence of `GATE_ORDER` holding every part-2 gate and `fix_proof`, both sides of the equivalence exercised | `test_blast_radius_fix_proof.py::test_the_lane_is_the_max_over_reasons_with_a_fix_signal`, `::test_eligible_iff_every_gate_passed_iff_low_with_a_fix_signal`, `::test_every_code_with_a_fix_signal_is_in_the_catalogue`, `::test_the_invariant_table_has_both_eligible_and_non_eligible_rows`, `::test_the_rendered_reason_names_the_fix_code` |
| Unsupplied → omitted | Without `fix_proof` the gate is omitted (not `null`), no `fix.*` reason is emitted, and a complete docs change stays `baseline.clean` / `low` / `eligible` with every listed gate `true`; the same holds with missing inputs and beside a migration; a supplied signal is always a boolean gate (`true` exactly for a non-fix or `proven`) | `test_blast_radius_fix_proof.py::test_no_signal_omits_the_fix_proof_gate_and_emits_no_fix_reason`, `::test_no_signal_omits_the_gate_whatever_else_the_change_holds`, `::test_a_supplied_signal_always_measures_the_gate` |
| Shared helper | `proven` evidence on a fix title → `{"required": True, "status": "proven"}` → `fix.proven`; each recorded status carried through to its code; no evidence on a fix → a missing-receipt status → `fix.no-receipt`; required for a default label, a configured label, a capitalised type and a whitespace-led title, not for a feature or a label outside a configured list | `test_blast_radius_fix_proof.py::test_the_shared_helper_*` |
| Verification tool agrees | `_run_lane` equals the packet lane for a fix without a receipt (`medium`) and is `low` for a proven fix | `test_blast_radius_fix_proof.py::test_the_verification_tool_lane_matches_the_packet_lane`, `::test_the_verification_tool_lane_is_low_for_a_proven_fix` |
| Approval gate completeness | A hand-built low packet whose checklist lacks `fix_proof` is refused by `low_risk_passing` and `clean_pass`; with every gate listed it selects `low_risk_passing`; a medium packet lacking `fix_proof` never reaches `clean_pass`, with it listed it does; a real feature-run packet reaches `low_risk_passing`; a real fix run without a receipt does not | `test_blast_radius_fix_proof.py::test_a_low_packet_whose_checklist_lacks_fix_proof_is_refused`, `::test_a_low_packet_with_every_gate_true_selects_low_risk_passing`, `::test_a_medium_packet_whose_checklist_lacks_fix_proof_never_reaches_clean_pass`, `::test_a_medium_packet_with_every_gate_listed_reaches_clean_pass`, `::test_a_feature_run_packet_reaches_low_risk_passing`, `::test_a_fix_run_packet_without_a_receipt_never_reaches_low_risk_passing` |
| Run packet | Title + `proven` evidence → `fix.proven`; title without evidence → `fix.no-receipt`; each recorded status → its code; a feature → `fix.not-required`; a default label; configured labels replace the defaults; a proven receipt on a non-fix stays `fix.not-required`; no new packet key | `test_blast_radius_fix_proof.py::test_a_fix_titled_run_*`, `::test_a_feature_run_is_not_required`, `::test_a_default_fix_label_makes_the_run_a_fix`, `::test_the_configured_fix_labels_replace_the_defaults`, `::test_a_proven_receipt_on_a_non_fix_run_is_still_not_required`, `::test_the_fix_proof_adds_no_packet_section` |
| Fix labels are base-side only | `ToolState.fix_labels` starts `None`. A non-operator-owned snapshot with `fixLabels: []` cannot switch off the `bug` label (`fix.no-receipt`), and its `[hotfix]` is ignored in favour of the defaults. An operator-owned snapshot's `[hotfix]` is honoured. Base-resolved `("hotfix",)` wins over a head that drops it and replaces the defaults. The verification tool reads the same labels. The resolver honours the run-start list on an operator-owned run with no read, reads the base commit at its SHA otherwise, and gives the defaults for a base without the key, a 404, a failed read or an unknown base SHA | `test_blast_radius_fix_proof.py::test_tool_state_starts_with_no_resolved_fix_labels`, `::test_a_head_only_empty_fix_labels_cannot_switch_off_label_detection`, `::test_a_head_only_fix_label_list_is_ignored_for_the_defaults`, `::test_an_operator_owned_snapshot_fix_label_list_is_honoured`, `::test_the_base_resolved_fix_labels_win_over_a_head_that_removes_them`, `::test_the_verification_tool_reads_the_same_base_side_fix_labels`; `tests/ci/test_red_green_settings.py::test_an_operator_owned_run_uses_the_run_start_fix_labels_without_a_read`, `::test_a_fork_run_reads_fix_labels_from_the_base_commit`, `::test_a_base_without_fix_labels_gives_the_defaults_not_the_head_list`, `::test_an_unreadable_base_config_gives_the_defaults`, `::test_an_unknown_base_sha_gives_the_defaults_without_a_read` |
| Reason messages carry the detail | A signal's `detail` (oversized, a fork name, a truncated diff, a SHA mismatch) appears in the `fix.receipt.invalid` / `fix.no-receipt` / `fix.receipt.mismatch` message; without a detail the message is still non-empty and never says `None`; the packet's reason shows `ToolState.red_green.detail`; the helper carries it | `test_blast_radius_fix_proof.py::test_the_reason_message_carries_the_evidence_detail`, `::test_a_signal_without_a_detail_still_has_a_message`, `::test_the_packet_reason_shows_the_recorded_evidence_detail`, `::test_the_shared_helper_carries_the_recorded_status` |
| Run record | One record line names the `fix.*` code | `test_blast_radius_fix_proof.py::test_the_run_record_names_the_fix_code` |
| Docs | `docs/blast-radius.md` *Fix proof* section; `docs/red-green-receipts.md` has the schema id, the 1 MB cap, the keys and no `${{`; REVIEW-CHECKS.md says the tests are never run; the receipt doc names `redGreen`, its `workflow` key and the fork rule; CHANGELOG `### Added` names `redGreen`; none of them still says `redGreenArtifacts`. The *Lane reasons* rows are enforced by the existing catalogue test | `test_blast_radius_fix_proof.py::test_the_blast_radius_doc_has_a_fix_proof_section`, `::test_the_receipt_doc_documents_the_format_and_the_cap`, `::test_review_checks_says_receipts_never_run_tests`, `::test_the_changelog_adds_the_receipts_under_unreleased`; `tests/classify/test_lane_reason_catalogue.py` |
| Post-review reader | `ingest_red_green_after_review` against a fake client: a proven receipt from the declared same-repository run is `proven`; a `wait-for-ci` state of `timeout`, `absent`, `skipped` or `pending` is `no-receipt` naming the state, and an unforwarded one says `not forwarded`, with nothing listed or downloaded; an incomplete listing says `incomplete` and downloads nothing; no GitHub client or no head SHA is `no-receipt` with no listing; a listing error is `no-receipt` naming the error type and never raises; no declaration records nothing and lists nothing | `tests/ci/test_red_green_after_review.py::test_the_reader_*`, `::test_an_incomplete_listing_records_no_receipt_and_downloads_nothing`, `::test_no_github_client_records_no_receipt`, `::test_no_head_sha_records_no_receipt`, `::test_a_listing_error_records_no_receipt_and_never_raises` |
| Post-review call site | Through `main._run_review_after_analyze` with the agent stubbed to write the review diff: the order is pre-agent lane, agent, roster, then exactly one run listing; `ToolState.red_green` is unset before the agent and `proven` after (removing the call fails it); the pre-agent lane is called once with `red_green=False`, and with that flag `ingest_ci_sarif_for_head_sha` neither downloads nor records a receipt | `test_red_green_after_review.py::test_the_receipt_is_read_once_after_the_agent_and_the_roster`, `::test_the_receipt_read_after_the_review_sets_tool_state`, `::test_the_pre_agent_lane_never_reads_the_receipt`, `::test_the_head_sha_ingest_reads_the_receipt_only_when_asked` |
| Skip-path writers | A setup-script `inconclusive` skip, a triage `skip` and an ignore-paths skip, each with a base declaration, record `no-receipt` whose detail says "could not be verified" and "the agent did not run" and names the workflow; without a declaration each stays `not-declared`; a recorded `proven` is never overwritten; neither the agent nor the post-review reader runs. The `lite` tier (real `_triage_gate`, lite driver and triage inputs stubbed) records the same unverified status, or `not-declared` without a declaration | `tests/ci/test_red_green_skip_paths.py::test_a_skip_path_*`, `::test_the_lite_tier_*` |
| Fix labels on the setup-script skip | A setup-script `inconclusive` skip still stores the base `fixLabels: [regression]` on `ToolState.fix_labels` before it returns | `test_red_green_skip_paths.py::test_the_setup_script_skip_still_resolves_the_base_fix_labels` |
| Unreadable base vs. no declaration | A base config read that fails (non-404), a base block that does not validate (`..` workflow), and an unknown base SHA each record `not-declared` with a detail naming the base and saying it "could not be read" (an unknown SHA may say "unknown"), never "declares no". A base without the block, or without a config file (404), keeps the "declares no" wording | `test_red_green_skip_paths.py::test_an_unreadable_base_says_it_could_not_be_read`, `::test_an_unknown_base_sha_says_the_base_could_not_be_read`, `::test_a_base_that_declares_nothing_keeps_the_declares_no_wording` |
| Trust story | The *Trust* section says a `pull_request` run executes head-side code (naming `conftest.py`) and that a receipt is no defence against an author with push access; the doc says to write the receipt inline in the declared workflow; the sample workflow still writes and uploads `red-green.json` but calls no `scripts/write_red_green_receipt.py`, which the doc no longer mentions; the "same question as who may change any other required check" sentence is gone | `tests/ci/test_red_green_trust_doc.py` |

## Matrix

| Layer | Happy path | Edge cases | Error handling |
| --- | --- | --- | --- |
| Unit | valid receipt; `proven` verdict; exact SHA match; `fix:` titles and labels; proven fix → `low` | cap boundary, UTF-8 bytes, 2 000 / 500 bounds, ordering, unicode, case, short SHAs, `fixture:` / `prefix:` | every `invalid` shape; `oversized` never decoded; unproven statuses escalate |
| Integration | collector → `RedGreenEvidence`; `ingest_ci_sarif_for_head_sha` → `ToolState.red_green`; settings YAML | failed run beside a successful one; another head SHA; blank names; uppercase receipt | failed download, missing artifact, bad zip, mismatch; no subprocess |
| Functional | `build_run_packet` → reasons and gate; run record line | configured labels replace defaults; proven receipt on a non-fix | fix without evidence → `fix.no-receipt`, `medium` |

## Not pinned (left to the implementation)

- Error message wording; only `kind` and a non-empty message are asserted.
- Whether the run record shows the status on the *Blast radius* line or its own
  line: one line must carry the `fix.*` code.
- Which zip member holds the receipt, beyond a JSON member named
  `red-green.json` being read.
- Several successful runs that each upload a receipt.

## Shared part-2 test amendments

The omitted-gate rule and the complete-checklist approval rule would have broken
part-2 tests that classify without any optional signal. Both lanes carry the
same amendment. The declared-scope lane's hunks are applied verbatim, and this
lane adds `fix_proof` on top:

- Checklist comparisons expect an ordered subsequence of `GATE_ORDER` holding
  every part-2 gate (`test_blast_radius_reasons.py::test_the_checklist_lists_every_gate_in_gate_order`,
  `test_blast_radius_signal_missing.py::test_gate_order_starts_with_the_missing_signal_table_gates`,
  `tests/evidence/test_shadow_compare_fixture_classifications.py`).
- The approval-route controls classify with a scope covering the change and a
  non-fix signal `{"required": False, "status": "not-required"}`
  (`test_blast_radius_signal_missing.py::test_a_measured_low_change_still_selects_low_risk_passing`,
  `::test_a_real_medium_classification_with_a_failed_gate_still_reaches_clean_pass`).
  Hand-built checklists come from `GATE_ORDER`.
- Direct callers of `classify_run_blast_radius` pass `scope` and `fix_proof`
  only when `inspect.signature` shows the keyword
  (`test_blast_radius_reasons.py`, `tests/evidence/test_run_packet.py`,
  `tests/mcp/test_commit_info_scope.py`).
- `tests/agents/test_gate_regressions_lane_c.py` records a declared scope when
  `ToolState` carries one. Its fix-proof signal comes from the packet itself,
  because the run title is not a fix.

- `test_blast_radius_reasons.py::CODE_CASES` ends with a `# fix proof (part 5)`
  block: one clean docs change per `fix.*` code, each carrying a `fix_proof`
  signal. `fix.not-required` and `fix.proven` are `low` and pass every gate; the
  four `medium` codes fail `fix_proof`. The catalogue-equality test keeps its
  assertion, so these rows are red until this lane's implementation. The
  declared-scope lane's `# declared scope (part 3)` block and its two consumer
  tweaks sit immediately before this one, taken verbatim. Its rows stay red on
  this branch until that lane's implementation merges. The gate-order check
  requires the `fix_proof` gate exactly when a row supplies a `fix_proof`
  signal, the same way it treats `scope`.

The shared hunks hold on `main`, with either lane alone, and after both merge.
The packet-level tests in `test_blast_radius_fix_proof.py` also declare a
covering scope when `ToolState` has `scope_declaration`, so a run's lane moves
only with the fix proof.

## Amendments

- An unsupplied `fix_proof` signal omits the gate from the checklist (not
  `null`) and emits no `fix.*` reason; a supplied signal is always a boolean
  gate. Tests: `test_no_signal_omits_the_fix_proof_gate_and_emits_no_fix_reason`,
  `::test_no_signal_omits_the_gate_whatever_else_the_change_holds`,
  `::test_a_supplied_signal_always_measures_the_gate`. Checklist-shape
  assertions now compare an ordered subsequence of `GATE_ORDER`.
- `classify_run_blast_radius` takes required keyword-only `scope` and
  `fix_proof`. Its direct tests were replaced by tests of the shared helper
  `fix_proof_signal_for_state` plus `classify_blast_radius`, and by the
  `build_run_packet` and verification-tool seams.
- `low_risk_passing` and `clean_pass` refuse a checklist that lacks any
  `GATE_ORDER` gate. Tests: the *Approval gate completeness* rows.
- `no-tests` on a fix maps to `fix.not-proven`. A capitalised type (`Fix:`)
  counts as a fix, and leading whitespace in a title is stripped.
- A non-fix signal may carry the status `not-required`, which the shared
  part-2 controls use. `test_a_non_fix_pull_request_is_not_required_whatever_the_status`
  covers it.
- The packet-level tests declare a covering scope once `ToolState` has
  `scope_declaration`, so they hold after the declared-scope lane merges.
- `review.fixLabels` is honoured only from the operator's base-side config, as
  `review.fastPath` and `review.ignorePaths` are. A head-only change is ignored:
  a fork cannot set `fixLabels: []` to switch off label-based fix detection.
  Run start resolves the list (`resolve_fix_labels`) onto `ToolState.fix_labels`;
  the packet and the verification tool read it. The `main.py` call site is not
  pinned by a test; the verifier audits it beside `_ignore_paths_gate`. Tests:
  the *Fix labels are base-side only* row.
- Receipt provenance (verifier finding). `ciEvidence.redGreenArtifacts` is
  replaced by `ciEvidence.redGreen` (`artifact`, `workflow`), honoured only from
  the base side and resolved at run start onto `ToolState.red_green_declaration`.
  A receipt counts only from the declared workflow's same-repository run, and
  only when the unfiltered change set leaves that workflow alone; any doubt
  fails closed. Archives are size-checked before download (2 MiB) and the member
  read is bounded. The reason messages carry the evidence `detail`. Tests: the
  *Receipt provenance*, *Declared workflow unchanged*, *Archive and member
  bounds*, *Base-side declaration*, *Run-start writers* and *Reason messages
  carry the detail* rows.
- Production timing (open for the implementer). The action-side receipt ingest
  runs in `_run_review_after_analyze` before the agent's `checkout_pr` writes the
  review diff, so a change-set check made at that moment always fails closed.
  The pins drive the collector with the diff already on `ToolState`. The
  implementation must make that true where the receipt is read, either by
  reading it after checkout or by supplying the change set beforehand.
- `test_the_fork_pr_added_workflow_forgery_never_proves_a_fix` now accepts a `medium` or `high` lane. Its fixture diff edits `.github/workflows/forged.yml`, which part 2 classifies as `paths.deployment` (`high`). The property under test is "never `low`", and the test still requires the `fix.no-receipt` reason itself to be `medium`.
- Round three (verifier findings). The post-review reader and its call site are
  now pinned (the *Post-review reader* and *Post-review call site* rows), which
  settles the production-timing item above: the receipt is read after the
  roster, once the agent has written the review diff. The skip-path and `lite`
  writers, the fix labels on the setup-script skip, the unreadable-base wording
  and the trust story have their own rows. A YAML parse failure on the base is
  not in the unreadable-base table: the shared config loader treats an
  unparseable file as an empty overlay (the defaults), so today it is
  indistinguishable from a base that declares nothing.
