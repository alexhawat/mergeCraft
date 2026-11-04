# Test plan — coded lane reasons and the blast-radius checklist

Part 2 of #1056. A blast-radius classification carries `reasons` (stable dotted
codes, each with the lane it forces after repository overrides and the small
isolated-source carve-out) and a `checklist` of gates in a fixed order whose
`passed` is `true`, `false` or `null` (not measured). `reason`, `lane`,
`auto_merge_lane`, `next_action` and `categories` stay for existing consumers.
The packet schema moves to `1.18.0`.

## Test strategy

Every test drives the public classifier (`classify_blast_radius`), the run's
diff classifier (`classify_run_blast_radius`), the gate predicates and rule
selection in `mergecraft.agents.gates`, or the run-record renderer
(`render_deterministic_review_block`). New module names (`LaneReason`,
`ChecklistGate`, `LANE_REASON_CATALOGUE`, `GATE_ORDER`) are read through an
`import_module` fixture, so the suite collects before they exist and each test
fails on its own. Change tables are plain dicts; malformed rows (a string for
`changed_paths`, a list for `diff_stats`) are deliberate.

The docs catalogue test parses the *Lane reasons* table in
`docs/blast-radius.md` and compares it with `LANE_REASON_CATALOGUE` through a
small drift helper. The helper is exercised with the real docs rows and the
real catalogue plus one injected code, one injected row and one wrong lane, so
the check is shown to trip in each direction.

## Coverage map

| Contract | What it proves | Tests |
| --- | --- | --- |
| Each code fires with its default lane | One change per catalogue code; the emitted reason carries the code, the catalogue default and a non-empty message | `tests/classify/test_blast_radius_reasons.py::test_each_code_fires_with_its_default_lane`, `::test_each_case_lane_is_the_catalogue_default`, `::test_the_case_table_exercises_every_catalogue_code` |
| A code above `low` fails its gate | Migrations, auth/security/payment/permissions, secrets/config/deployment, irreversible infra, public API, dependencies, tests and review config each fail the named gate; a missing input fails `inputs` | `test_blast_radius_reasons.py::test_a_code_above_low_fails_its_gate` |
| A low code passes every gate | Generated output, the small isolated-source carve-out and a clean docs change are `low`, `eligible`, every gate `true` | `test_blast_radius_reasons.py::test_a_low_code_alone_passes_every_gate` |
| Gate order | `GATE_ORDER` starts with the ten gates (the nine planned ones, then `source`) in their fixed order, no duplicates; every checklist lists exactly `GATE_ORDER` | `test_blast_radius_reasons.py::test_gate_order_starts_with_the_locked_gates`, `::test_the_checklist_lists_every_gate_in_gate_order` |
| Complete inputs measure every gate | With changed paths and diff statistics, `inputs` is `true` and no gate is `null` | `test_blast_radius_reasons.py::test_a_complete_change_measures_every_gate` |
| `lane == max(reason.lane)`, at least one reason | Over every code case, empty inputs, a migration without stats, generated plus migration, the carve-out, a blocked carve-out, review config under `src/`, and four overrides | `test_blast_radius_reasons.py::test_the_lane_is_the_max_over_reasons` |
| `eligible` ⇔ every gate `true` ⇔ `lane == "low"` | Same table; a guard test proves the table holds both eligible and non-eligible rows so the equivalence is not vacuous | `test_blast_radius_reasons.py::test_eligible_iff_every_gate_passed_iff_low`, `::test_the_invariant_table_has_both_eligible_and_non_eligible_rows` |
| Codes come from the closed catalogue | No emitted code is outside `LANE_REASON_CATALOGUE` | `test_blast_radius_reasons.py::test_every_reason_code_is_in_the_catalogue` |
| An override is a visible reason | A dependency override to `low` makes the reason `low`, says "repository override", passes the `dependencies` gate and leaves the catalogue default at `medium`; an override up to `high` raises the `tests.missing` reason and says so | `test_blast_radius_reasons.py::test_an_override_to_low_is_a_visible_reason_and_passes_its_gate`, `::test_an_override_up_raises_the_reason_lane_and_says_so` |
| Floors that an override cannot lower | A `review_config` override to `low` still gives `medium` / `assisted` with the gate failing; an unknown `signal_missing` override key cannot lower a missing-input reason | `test_blast_radius_reasons.py::test_a_review_config_override_cannot_lower_its_floor`, `::test_a_signal_floor_cannot_be_lowered_by_an_unknown_override_key` |
| The carve-out is a reason | A ≤5-line single-file source edit emits `source.small_isolated`, every reason is `low`, the `tests` gate passes; a source override blocks it; review config under `src/` is never carved out | `test_blast_radius_reasons.py::test_the_small_isolated_carve_out_is_a_reason_and_the_tests_gate_passes`, `::test_a_source_override_blocks_the_carve_out_and_fails_the_tests_gate`, `::test_review_config_under_src_is_not_carved_out` |
| `source.changed` lifts a broad source edit | A source edit with tests has no category but is `medium` with a failing gate | `test_blast_radius_reasons.py::test_source_changed_with_tests_is_medium_and_not_every_gate_passes` |
| Compatibility summary | `reason` names every code and keeps the existing sentence; `categories` keeps `signal_missing` | `test_blast_radius_reasons.py::test_the_rendered_reason_names_every_code_and_keeps_the_sentence`, `::test_a_missing_signal_reason_keeps_the_missing_input_sentence` |
| Typed models | `LaneReason` holds code/lane/message, rejects an unknown lane, an extra field and a missing code (error location asserted); `ChecklistGate` accepts `true`/`false`/`null` and round-trips; an unmeasured gate dumps as JSON `null`; a classification round-trips | `test_blast_radius_reasons.py::test_lane_reason_*`, `::test_checklist_gate_accepts_true_false_and_unknown`, `::test_an_unmeasured_gate_serialises_as_json_null`, `::test_a_classification_round_trips_reasons_and_checklist` |
| Run diff seam | `classify_run_blast_radius` on a migration diff emits `paths.migrations` with a measured checklist | `test_blast_radius_reasons.py::test_the_run_diff_classifier_emits_reasons_and_a_measured_checklist` |
| Run record line | The deterministic run record prints the lane and the reason codes on one line, and the line follows the classification | `test_blast_radius_reasons.py::test_the_run_record_prints_the_lane_and_its_codes_on_one_line`, `::test_the_run_record_line_follows_the_classification` |
| Missing inputs are unknown, not green | For every missing-signal case: the exact checklist (path gates `null` without paths; path-only gates measured without stats; a gate failed from paths stays `false`; `inputs` `false`), the matching `signal.missing.*` reason at `medium`, and the invariants | `tests/classify/test_blast_radius_signal_missing.py::test_a_missing_signal_marks_its_unmeasured_gates_unknown`, `::test_a_missing_signal_emits_its_coded_reason`, `::test_a_missing_signal_holds_the_lane_and_eligibility_invariants`, `::test_a_gate_failed_from_paths_stays_false_without_diff_stats`, `::test_a_path_only_gate_is_measured_without_diff_stats`, `::test_a_complete_low_change_passes_every_gate`, `::test_gate_order_starts_with_the_missing_signal_table_gates` |
| The gate reads `inputs` | `low_risk_passing` and `clean_pass` refuse a packet whose checklist `inputs` is `false` or `null` even when its categories look measured; a measured checklist still reaches both rows | `test_blast_radius_signal_missing.py::test_low_risk_passing_refuses_a_checklist_without_measured_inputs`, `::test_clean_pass_refuses_a_medium_checklist_without_measured_inputs`, `::test_a_checklist_with_measured_inputs_still_reaches_low_risk_passing`, `::test_a_checklist_with_measured_inputs_still_reaches_clean_pass` |
| Older packets decide as before | A `1.17.0` packet whose blast radius has no `reasons`/`checklist` still validates and selects `low_risk_passing`, `clean_pass` or `needs_human_review` exactly as before | `test_blast_radius_signal_missing.py::test_a_packet_written_before_the_checklist_decides_as_before` |
| Catalogue contents | Every locked code is present with its default lane; lanes are known; codes are dotted lowercase | `tests/classify/test_lane_reason_catalogue.py::test_the_catalogue_carries_every_locked_code_with_its_default_lane`, `::test_every_catalogue_lane_is_a_known_lane`, `::test_every_code_is_a_stable_dotted_lowercase_name` |
| Catalogue ↔ docs | The *Lane reasons* table has the columns `code`, `default lane` and `when`, lists no code twice, and matches the catalogue; an added code, an added row and a wrong lane each trip the check | `test_lane_reason_catalogue.py::test_the_docs_table_*`, `::test_a_code_added_without_a_docs_row_is_caught`, `::test_a_docs_row_without_a_code_is_caught`, `::test_a_docs_row_with_the_wrong_lane_is_caught` |
| Checklist docs | The *Checklist* section names every gate and states the `null` rule and the `eligible` equivalence | `test_lane_reason_catalogue.py::test_the_docs_checklist_section_names_every_gate_and_the_null_rule` |
| Packet schema `1.18.0` | The constant and the field default are `1.18.0`; `docs/evidence-packet.md` states it, has a `1.18.0` history row naming `reasons` and `checklist`, and documents the real `blast_radius` shape; a packet round-trips both fields | `tests/evidence/test_packet_schema_version.py` |
| Earlier bump history | The analyzers-section test keeps asserting the version is at least `1.14.0` instead of pinning the exact current version | `tests/evidence/test_packet_dispositions.py::test_schema_version_is_bumped_for_the_analyzers_section` |

## Matrix

| Layer | Happy path | Edge cases | Error handling |
| --- | --- | --- | --- |
| Unit | each code with its default lane; low codes pass every gate | carve-out; overrides up and down; generated plus high; empty `diff_stats` | malformed `LaneReason` rows; unknown override key |
| Integration | run diff classifier; packet round trip | `1.17.0` packet without the new fields | gate refuses `inputs` `false` / `null` |
| Functional | run record line names lane and codes | review-config line differs from a migration line | catalogue drift in either direction |

## Not pinned (left to the implementation)

- The label and exact wording of the run-record line: the tests require one
  line carrying the lane and every code.
- Whether a reason that the carve-out lowers (for example `tests.missing`) is
  still emitted at `low` or dropped: every reason in that case must be `low`.
- With `changed_paths` missing but diff text present, whether a diff-only
  signal (destructive SQL) fails its gate or leaves it `null`.

## Amendments

- The `source` gate follows `review_config` in `GATE_ORDER`: `source.changed` fails it and `source.small_isolated` passes it. It reads paths and line counts, so it is `null` without either. The missing-signal checklist table now includes it, with `source` `false` for a lone source file without stats. The table compares only the gates it names, so gates appended later do not break it. A separate test pins the table's gates as the prefix of `GATE_ORDER`.
- A generated path exempts only itself. A non-generated `src/` path still emits `source.changed`, plus `tests.missing` when no test changed, whatever generated siblings sit beside it (`docs/generated/…`, `src/generated/…`). A change made only of generated paths stays `paths.generated` / `low`. Tests: `test_blast_radius_reasons.py::test_a_generated_sibling_does_not_mask_a_source_change`, `::test_a_change_of_only_generated_paths_stays_low`.
- The small isolated-source carve-out does not apply beside a `high` reason: a ≤5-line source edit next to a migration emits no `source.small_isolated`, and `tests.missing` stays `medium`. Test: `test_blast_radius_reasons.py::test_the_carve_out_is_not_emitted_beside_a_high_reason`.
- The run-record line ends with `not measured:` and the `null` gates in checklist order, and carries no suffix when every gate was measured. Tests: `test_blast_radius_reasons.py::test_the_run_record_line_lists_the_unmeasured_gates`, `::test_the_run_record_line_has_no_suffix_when_every_gate_is_measured`.
- `low_risk_passing` requires every checklist gate `true` when a checklist is present. A hand-built `low` packet with `inputs` `true` and any other gate `null` or `false` is refused. `clean_pass` refuses a `low` packet with any `null` gate. Two controls: a real `medium` classification (which always has a `false` gate) still reaches `clean_pass`, and a packet with an empty checklist keeps the legacy `low_risk_passing` route. Tests: `test_blast_radius_signal_missing.py::test_low_risk_passing_refuses_a_low_lane_with_any_gate_not_passed`, `::test_clean_pass_refuses_a_low_lane_with_an_unmeasured_gate`, `::test_the_issue_example_low_lane_with_unmeasured_tests_never_auto_merges`, `::test_a_real_medium_classification_with_a_failed_gate_still_reaches_clean_pass`, `::test_a_pre_checklist_low_packet_keeps_the_legacy_route`.
- The shadow-compare replay's hand-built classifications carry at least one reason and a full checklist that satisfy the lane invariants. Test: `tests/evidence/test_shadow_compare_fixture_classifications.py`.
- Open: `diff_stats` present but without any diff-text key. Marking `migrations`, `secrets_config_deployment` and `irreversible_infra` `null` there means, through the eligibility equivalence, that such a change can never be `low`. That would change many fixtures that are `low` today (line counts only, or `{}`), plus the `is_trivial` result for all-generated changes. Not pinned until the lane consequence is decided.
