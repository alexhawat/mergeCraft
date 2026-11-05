# Test plan — declared scope paths drive the scope gate

Part 3 of #1056. A pull request (or an issue it closes) may end its body with a
`Scope paths:` block of globs. The run parses it once, records it on the run
state, and the blast-radius classifier checks every changed path against it.
The body is untrusted: globs are bounded, fail closed, are never used to open a
file and never appear outside the nonce fence or in a reason message.

## The scope gate

| Change set | `scope` gate | Reason |
| --- | --- | --- |
| no `scope` key (a library caller) | left out of `checklist` | none; nothing else changes |
| `declared=False` (no block in the PR body or its closing issues) | `null` | `scope.unknown` (`medium`) |
| `declared=True`, no globs | `false` | `scope.undeclared` (`medium`) |
| `invalid=True` | `false` | `scope.invalid` (`medium`) |
| every changed path (both rename images) matches a glob | `true` | `scope.within` (`low`) |
| any path outside | `false` | `scope.drift` (`medium`), at most ten paths named |

The run always supplies a signal: `build_run_packet` and the verification tool
build it from `ToolState.scope_declaration` (`None` or no block → `declared=False`),
so a run with no declaration has a `null` gate, a `scope.unknown` reason at
`medium`, and is never `eligible` — the same shape as `signal.missing.*`, which
keeps `lane == max(reasons)` and `eligible` ⇔ every gate `true` ⇔ `low`. The
approval rows (`low_risk_passing`, `clean_pass`) refuse a checklist that is
missing any gate of `GATE_ORDER`. `scope` sits after the ten part-2 gates; later
gates may follow it.

## Test strategy

New names (`parse_scope_paths`, `ScopeDeclaration`, `ScopeSignal`, the `scope`
key on `ChangeSet`, `ToolState.scope_declaration`, `main._record_scope_declaration`,
`mergecraft.scm.types.LinkedIssue`) are read through `import_module` fixtures or
`getattr`, so the suite collects before they exist and each test fails on its
own. Tests that need the run state to carry a field that does not exist yet set
it with `setattr` (the state is `slots`-backed, so the set itself fails until the
field is added).

The classifier is driven with plain-dict change sets. The run seam is driven
through `build_run_packet` on a `ToolContext` shaped like the one the run holds
at the end, on real diff text (so rename sources come from
`changed_paths_from_diff`); the full signature of `classify_run_blast_radius` is
not pinned. The verification tool is driven through its lane helper on the same
context. The `main.py` seam is driven directly (`_record_scope_declaration`) and
through `_run_review_after_analyze` with the setup steps and the fast-path gate
replaced, to show the declaration exists before the gate decides.

**Linked issues.** The issues the pull request closes are read once at run start
by the linked-issue read into `ToolState.linked_issues: tuple[LinkedIssue, ...] |
None` (`LinkedIssue`: frozen, `number`, `author_login`, `body`; `()` closes
nothing, `None` not read), the field and shape the policy-evidence producers'
test plan states. The scope seam reads each issue's `.body` in order after the
pull request body. These tests set that field directly with `LinkedIssue` rows
and never exercise the GraphQL read.

Every new test is revert-sensitive: each one fails on the anchor and passes only
once the behaviour exists. No test asserts only an absence; checks like "no
reason echoes the glob" sit beside a positive check on the emitted code.

## Coverage map

| Contract | What it proves | Tests |
| --- | --- | --- |
| Block forms | Bare, bold, `##`, `###`, any case, `-` and `*` bullets, fenced (with and without an info string), a blank line before the first item, backticked items, indented items: globs in order, trimmed, backticks removed | `tests/requirements/test_scope_paths.py::test_each_block_form_declares_its_globs_in_order` |
| Declaration type | Frozen dataclass with exactly `declared`, `globs`, `source_ref`, `rejected` | `test_scope_paths.py::test_the_declaration_is_a_frozen_dataclass_with_the_locked_fields` |
| CRLF | List and fenced bodies with `\r\n` parse, no `\r` in a glob | `test_scope_paths.py::test_a_crlf_body_parses_without_carriage_returns`, `::test_a_crlf_fenced_body_parses` |
| Where the block stops | A blank line after the first item, the next heading, the closing fence; list items before the header are not collected | `test_scope_paths.py::test_the_block_stops_at_a_blank_line_after_the_first_item`, `::test_the_block_stops_at_the_next_heading`, `::test_a_fenced_block_stops_at_its_closing_fence`, `::test_list_items_before_the_block_are_not_collected` |
| No block / empty block | No header → `declared=False`; a header with no items → `declared=True, globs=()` | `test_scope_paths.py::test_a_body_without_a_scope_block_declares_nothing`, `::test_a_header_with_no_items_is_declared_with_no_globs` |
| Count bound | 64 globs accepted; 65 → `declared=True, globs=()`, every one of the 65 in `rejected` | `test_scope_paths.py::test_sixty_four_globs_is_within_the_bound`, `::test_sixty_five_globs_declares_nothing` |
| Per-glob bounds | 200 characters accepted; 201, a `..` segment (middle, leading, trailing), a leading `/`, NUL, tab, ESC and DEL each fail the whole declaration with exactly the offender in `rejected` | `test_scope_paths.py::test_a_two_hundred_character_glob_is_within_the_bound`, `::test_a_bound_violation_declares_nothing_and_names_the_offender` |
| Wildcard-only globs | `*`, `**`, `**/*`, `**/*.*` declare nothing (`rejected` names it) | `test_scope_paths.py::test_a_wildcard_only_glob_declares_nothing` |
| Backticks | A glob wrapped in backticks is unwrapped before validation (`` `**` ``, `` `src/../etc` ``, `` `/etc/passwd` `` are rejected) and stored without them | `test_scope_paths.py::test_a_backticked_glob_is_unwrapped_before_it_is_validated`, `::test_a_backticked_glob_is_stored_without_its_backticks` |
| Ordinary globs | Dots inside a name, unicode, `**/*.py`, `*.md`, a class, `?` are accepted | `test_scope_paths.py::test_ordinary_globs_are_accepted` |
| Globs are data | Parsing never reads, opens, globs or stats a path (`Path.read_text`/`open`/`glob`/`exists`/`is_file`, `open`, `glob.glob` all refuse) | `test_scope_paths.py::test_parsing_never_opens_a_file` |
| `IngestResult.scope` | Ingest carries the declaration; the scope globs are not mistaken for acceptance criteria; no block → `declared=False` | `test_scope_paths.py::test_ingest_result_carries_the_scope_declaration`, `::test_ingest_result_without_a_block_carries_an_undeclared_scope` |
| Fenced | The glob appears once in `fenced_text`, between the nonce fence's open and close lines | `test_scope_paths.py::test_the_scope_globs_only_appear_inside_the_nonce_fence` |
| New classifier names | `ScopeSignal` keys and types; `ChangeSet.scope` optional and typed; catalogue codes and default lanes; `scope` once, after the unchanged part-2 gates | `tests/classify/test_blast_radius_scope.py::test_scope_signal_is_a_typed_dict_with_the_locked_keys`, `::test_change_set_gains_an_optional_scope_key`, `::test_the_catalogue_carries_the_scope_codes_with_their_default_lanes`, `::test_scope_comes_after_the_part_two_gates_which_are_unchanged` |
| Gate listed when supplied | Within, drift, undeclared, invalid, not-declared and no-inputs signals all list `scope`, in `GATE_ORDER` order, beside every part-2 gate | `test_blast_radius_scope.py::test_a_supplied_signal_always_lists_the_scope_gate` |
| No signal: library callers unchanged | Without a `scope` key the gate is left out, no `scope.*` reason, a complete docs change stays `low` and `eligible` | `test_blast_radius_scope.py::test_without_a_scope_key_the_gate_is_left_out_and_nothing_else_changes` |
| Within | Every path inside → `scope.within` at `low`, gate `true`; a low change in scope is `eligible` with every gate `true`; a source change in scope still `medium` with gate `true` | `test_blast_radius_scope.py::test_a_change_inside_its_declared_globs_passes_the_scope_gate`, `::test_a_low_change_inside_its_scope_is_eligible_with_every_gate_true`, `::test_a_scope_gate_passes_beside_a_medium_source_reason` |
| `**` crosses directories | `src/**` and `src/**/*.py` match `src/a/b/c.py`; `src/**` and `src/**/*.py` match `src/c.py` (zero directories); `docs/*.md`, an exact path and `**/conftest.py` match | `test_blast_radius_scope.py::test_globs_match_across_directories` |
| Drift | One out-of-scope path → `scope.drift` at `medium`, `assisted`, only the `scope` gate not `true`, message names the outside path and not the inside one; a rename source outside → drift; at most ten paths listed; three are all listed | `test_blast_radius_scope.py::test_one_out_of_scope_path_is_drift_even_when_everything_else_is_low`, `::test_a_rename_source_outside_the_globs_is_drift`, `::test_drift_lists_at_most_ten_out_of_scope_paths`, `::test_drift_lists_every_path_when_there_are_ten_or_fewer` |
| Undeclared / invalid | No globs → `scope.undeclared`, never `eligible`, gate `false`; `invalid` → `scope.invalid` (not `undeclared`), gate `false`; `invalid` wins over matching globs; `Scope paths: **` end to end → `scope.invalid`, never `eligible` | `test_blast_radius_scope.py::test_a_declaration_without_globs_is_undeclared_and_never_eligible`, `::test_an_invalid_declaration_is_invalid_and_never_eligible`, `::test_an_invalid_flag_wins_over_globs_that_would_match`, `::test_a_declared_match_everything_glob_never_passes_the_gate` |
| Not declared | `declared=False` → `scope.unknown` at `medium` (the only `scope.*` reason), gate `null`, lane `medium`, `assisted`; globs carried by such a signal are ignored; a scope with no changed paths is not measured (no vacuous `within`) | `test_blast_radius_scope.py::test_a_not_declared_signal_is_scope_unknown_at_medium_with_the_gate_null`, `::test_a_not_declared_signal_ignores_any_globs_it_carries`, `::test_a_scope_without_changed_paths_is_not_measured` |
| A scope never widens | A `high` category inside its scope stays `high`/`forbidden` (migrations, deployment, terraform); `high` beats drift; a declared scope leaves a failing `dependencies` gate failing | `test_blast_radius_scope.py::test_a_high_category_still_wins_inside_its_scope`, `::test_a_high_category_still_wins_over_drift`, `::test_a_declared_scope_cannot_pass_a_failing_gate` |
| No unfenced glob | No reason message and not the rendered `reason` contains a declared glob (within, drift, invalid) | `test_blast_radius_scope.py::test_no_reason_message_renders_a_declared_glob` |
| Part-2 invariants with a scope | `lane == max(reasons)`, codes in the catalogue, `eligible` ⇔ every gate `true` ⇔ `low`, over within / drift / undeclared / invalid / not-declared (docs, migration, small isolated source) / high / source / carve-out / missing-input rows that all carry a scope signal; the table has both sides | `test_blast_radius_scope.py::test_the_lane_is_the_max_over_reasons_with_a_scope`, `::test_eligible_iff_every_gate_passed_iff_low_with_a_scope`, `::test_the_scoped_invariant_table_has_both_sides` |
| Packet seam | `build_run_packet` classifies against `ToolState.scope_declaration`: within → `eligible`; drift names the path; a rename whose source is outside → drift naming the source; both images inside → `eligible`; rejected globs → `scope.invalid`; no declaration, or a body without a block → gate `null`, `scope.unknown`, `medium`, `assisted`, not `low_risk_passing` | `test_blast_radius_scope.py::test_the_run_packet_classifies_against_the_recorded_declaration`, `::test_the_run_packet_reports_drift_from_the_recorded_declaration`, `::test_the_run_packet_counts_a_rename_source_against_the_scope`, `::test_the_run_packet_passes_a_rename_with_both_images_in_scope`, `::test_the_run_packet_marks_a_rejected_declaration_invalid`, `::test_the_run_packet_without_a_declaration_leaves_the_scope_gate_unknown`, `::test_the_run_packet_with_an_unparsed_body_leaves_the_scope_gate_unknown` |
| Verification tool seam | The judge's lane follows the recorded declaration: within → `low`, drift → `medium` | `test_blast_radius_scope.py::test_the_verification_tool_lane_reads_the_recorded_declaration` |
| Approval rows need every gate | A hand-built `low` packet with every gate `true` but no `scope` row is neither `low_risk_passing` nor `clean_pass` (with the row it is `low_risk_passing`); a `medium` packet without the row is not `clean_pass` (with it, it is) | `test_blast_radius_scope.py::test_a_low_packet_whose_checklist_lacks_scope_never_selects_low_risk_passing`, `::test_a_medium_packet_whose_checklist_lacks_scope_never_selects_clean_pass` |
| Source order | The PR body wins (`source_ref == "pr_description"`); otherwise the first closing issue with a block (`source_ref` starts `linked_issue`); no PR body → issues; an invalid or empty body declaration is not replaced by an issue's; no block anywhere → not declared; unread issues still honour the body; CRLF body | `tests/review/test_declared_scope_seam.py::test_the_pull_request_body_declaration_wins`, `::test_the_first_closing_issue_with_a_block_is_used_when_the_body_has_none`, `::test_a_run_without_a_pull_request_body_reads_the_closing_issues`, `::test_an_invalid_body_declaration_is_not_widened_by_a_closing_issue`, `::test_an_empty_body_declaration_is_not_replaced_by_a_closing_issue`, `::test_no_block_anywhere_records_an_undeclared_scope`, `::test_unread_closing_issues_still_honour_the_body`, `::test_a_crlf_body_is_read` |
| Read failures | No tool state → nothing happens; a parser that raises → `scope_declaration is None`, no exception; a fresh run state has `None` | `test_declared_scope_seam.py::test_a_run_without_tool_state_is_left_alone`, `::test_a_failing_read_leaves_the_scope_unknown_and_never_raises`, `::test_a_fresh_run_state_has_no_scope_declaration` |
| Wiring | `_run_review_after_analyze` has recorded the declaration when the fast-path gate runs | `test_declared_scope_seam.py::test_the_declaration_is_recorded_before_the_fast_path_gate` |
| Hidden blocks | A `Scope paths:` block inside an HTML comment or a code fence (backticks or tildes) is not honoured; a visible block beside a hidden one is the declaration; an unclosed fence stops at the next `##` heading | `tests/requirements/test_scope_paths.py::test_a_block_inside_an_html_comment_or_a_code_fence_is_not_honoured`, `::test_the_visible_block_is_the_declaration_beside_a_hidden_one`, `::test_an_unclosed_fence_does_not_swallow_the_next_heading` |
| Comment-triggered runs | On an `issue_comment` or review-comment run the pull request body wins over a `Scope paths:` block in the comment (`source_ref="pr_description"`); the PR body is read from `issue.body` on a comment on a pull request; a block only in the comment declares nothing | `tests/review/test_declared_scope_seam.py::test_an_issue_comment_run_reads_the_pull_request_body_not_the_comment`, `::test_a_review_comment_run_reads_the_pull_request_body_not_the_comment`, `::test_a_pr_comment_run_records_the_declaration_in_the_issue_body`, `::test_a_block_only_in_the_comment_declares_nothing` |
| Matcher time on hostile globs | `path_full_matches_glob` and `path_matches_glob` on a run of twelve `**/` segments against a 30-segment path, `*a` ×8 `*b` against a 60-character segment, and the 44-character glob that stalled the run packet each return the right answer (miss and hit) in under 50 ms; each case runs in a fresh interpreter with a 10 s deadline so a regression fails fast | `tests/utils/test_path_globs.py::test_a_hostile_glob_matches_in_linear_time_with_the_right_answer` |
| Run time on a hostile body | Parsing a body of 64 such globs (all within the bounds) and classifying two deep paths against them finishes in under a second and reports `scope.drift`; 30 s deadline | `tests/classify/test_blast_radius_scope.py::test_sixty_four_hostile_globs_parse_and_classify_in_under_a_second` |
| `**` crosses directories (pipeline matcher too) | `.github/**` matches `.github/workflows/ci.yml`, `a/**/d.py` matches `a/b/c/d.py` and `a/d.py`, through both matchers; neither matches outside the tree, and `*` stays in one segment; the CHANGELOG says `changed_paths matches` predicates now cross directories | `tests/utils/test_path_globs.py::test_double_star_crosses_directories`, `::test_double_star_does_not_match_outside_its_tree`; `test_blast_radius_scope.py::test_the_changelog_says_changed_paths_predicates_now_cross_directories` |
| Root anchoring | `tests/**` does not match `src/tests/x.py`, `README.md` does not match `docs/README.md`, `*.md` does not match `docs/a.md` — in `path_full_matches_glob` and as `scope.drift` through the classifier (the pipeline matcher keeps its right-anchored match) | `tests/utils/test_path_globs.py::test_the_scope_matcher_is_anchored_at_the_root`; `test_blast_radius_scope.py::test_a_glob_does_not_match_a_deeper_path_with_the_same_tail` |
| No import cycle | `mergecraft.main`, `mergecraft.config.settings`, `mergecraft.classify.triage`, `mergecraft.fast_path` and `mergecraft.classify` each import first in a fresh interpreter (`python -I -c`); so does every module under `mergecraft.classify`, `mergecraft.config` and `mergecraft.utils` (eight at a time; a missing third-party extra is skipped). A sweep over all modules takes about two minutes and is not run | `tests/classify/test_fresh_imports.py` |
| Plan mode | The Plan template has exactly one `Scope paths:` checklist line naming globs and the end of the plan body, inside the checklist; both providers render it; Plan is the only mode that asks | `tests/modes/test_plan_scope_paths.py` |
| Plan template snapshot | The byte-identical snapshot test allows exactly that one added line in Plan and nothing else | `tests/test_modes.py::test_mode_prompt_text_is_byte_identical_after_split` |
| Docs | `docs/blast-radius.md` *Declared scope* section states the block, the bounds (64, 200, `..`, leading `/`, control characters, `**`), renames, the five codes and `null`; the *Checklist* table has a `scope` row failed by `scope.drift`; `REVIEW-CHECKS.md` *Blast-radius merge lanes* names the block and `scope.drift`. The *Lane reasons* rows are enforced by the existing catalogue test, not duplicated | `test_blast_radius_scope.py::test_the_blast_radius_doc_has_a_declared_scope_section_stating_the_bounds`, `::test_the_checklist_section_says_what_fails_the_scope_gate`, `::test_review_checks_describes_the_scope_gate_under_blast_radius_lanes`; `tests/classify/test_lane_reason_catalogue.py` |
| Changelog | An `## [Unreleased]` / `### Changed` bullet says a pull request without a declared scope cannot reach `eligible` | `test_blast_radius_scope.py::test_the_changelog_says_an_undeclared_scope_cannot_reach_eligible` |

## Matrix

| Layer | Happy path | Edge cases | Error handling |
| --- | --- | --- | --- |
| Unit | every block form; within; drift; `**` across directories | CRLF; 64/65 globs; 200/201 chars; `..` inside a name vs as a segment; unicode; blank line before the first item; ten vs twelve drift paths; no paths with a scope; no `scope` key | every bound violation fails closed with the offender named; wildcard-only globs; `invalid` beats matching globs |
| Integration | packet built from the recorded declaration; rename images; verification lane | no declaration; a body without a block; a checklist missing `scope` on the approval rows | rejected globs on the packet → `scope.invalid` |
| Functional | run start records the body's declaration before the fast-path gate | issue fallback order; no PR body; unread issues | parser raising never fails the run; a later source never widens an invalid or empty declaration |

## Not pinned (left to the implementation)

- The helper that turns `ToolState.scope_declaration` into a `ScopeSignal` (the
  packet and verification tests fix the outcome: `rejected` → `invalid`, `None`
  → `declared=False`), and the full signature of `classify_run_blast_radius`.
- The exact `source_ref` for a closing issue beyond its `linked_issue` prefix.
- The wording of every reason message, beyond the paths a drift message names.

## Amendments to existing tests

- Gate-order checks no longer expect every checklist to equal `GATE_ORDER`: a
  gate fed by an optional signal (`scope`) is listed only when the signal is
  supplied. They now pin that the checklist is `GATE_ORDER` in order with only
  such gates left out, and that every part-2 gate is present.
  `tests/classify/test_blast_radius_reasons.py::test_the_checklist_lists_every_gate_in_gate_order`
  (also: no `scope` row without a `scope` key),
  `tests/classify/test_blast_radius_signal_missing.py::test_gate_order_starts_with_the_missing_signal_table_gates`,
  `tests/evidence/test_shadow_compare_fixture_classifications.py::test_each_fixture_classification_has_reasons_and_a_full_checklist`.
- `classify_run_blast_radius` takes a required `scope` keyword. Its direct
  callers in tests pass an undeclared signal when the keyword exists (checked
  with `inspect.signature`), which leaves every part-2 assertion as it was:
  `tests/classify/test_blast_radius_reasons.py::test_the_run_diff_classifier_emits_reasons_and_a_measured_checklist`,
  `tests/evidence/test_run_packet.py::TestBlastRadiusFromDiff`,
  `tests/mcp/test_commit_info_scope.py::test_blast_radius_survives_head_inspection`.
- The approval rows need every gate in `GATE_ORDER`, so the routable controls
  supply one: the hand-built classification in
  `tests/classify/test_blast_radius_signal_missing.py` lists every gate of
  `GATE_ORDER` (not the ten part-2 gates);
  `::test_a_measured_low_change_still_selects_low_risk_passing` and
  `::test_a_real_medium_classification_with_a_failed_gate_still_reaches_clean_pass`
  classify a change with a declared scope it is inside; and
  `tests/agents/test_gate_regressions_lane_c.py::test_low_risk_passing_is_reachable_from_build_run_packet`
  records a declaration covering its diff when the run state has the field.
- `tests/test_modes.py::test_mode_prompt_text_is_byte_identical_after_split`:
  Plan is compared with its one `Scope paths:` line removed; every other mode
  stays byte-identical.

Each amended test stays green on the current tree and after the scope gate
exists.
