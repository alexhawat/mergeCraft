# Review convergence — test plan

Wave plan: `.ignorelocal/waves/review-convergence-wave-plan.md`
Worktree: `mergecraft-rc-review-convergence` @ `wave/rc-review-convergence` (base `fc0a8a65`)

## W9.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W9.2: …", strict=False)` | 3 RED pins below | W9.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

### Compatibility pins (pass on baseline `fc0a8a65`)

| Test | Why it is green today |
|------|------------------------|
| `test_round_budgets_default_preserves_current_totals` | D1 invariant — flat defaults unchanged until `review.roundBudgets` opts in |
| `test_budget_exhaustion_is_still_inconclusive_never_partial_approval` | D12 — `budget_exhaustion_outcome` already maps exhaustion to `inconclusive` |

## Contract → test matrix (W9.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| RC12 — round 1 deep allocation | W9 definition | Unit | `test_first_review_gets_the_deep_allocation` |
| RC12 — incremental taper | W9 definition | Unit | `test_incremental_rounds_taper` |
| D1 — default flat totals | Decisions D1 | Unit (invariant) | `test_round_budgets_default_preserves_current_totals` |
| D12 — exhaustion → inconclusive | `run_bounds.py:232-235` | Unit (invariant) | `test_budget_exhaustion_is_still_inconclusive_never_partial_approval` |
| RC12 — subagent budget scales | W9.2b registry | Unit | `test_subagent_budget_scales_with_the_round` |

## Named symbols this suite pins (post-W9.2)

| Symbol | Module | Test |
|--------|--------|------|
| `review.round_budgets` | `config/settings.py` | taper + default-flat tests |
| `resolve_run_bounds(..., round_index=…)` | `utils/run_bounds.py` | deep allocation + taper tests |
| `effective_agent_limits(..., round_index=…)` | `agents/registry.py` | subagent scaling test |
| `budget_exhaustion_outcome` | `utils/run_bounds.py` | exhaustion invariant test |
| Round index source | `mcp/checkout.py:364-376` | W9.2c — not pinned in W9.1 |

## Collection target (W9.1)

`tests/utils/test_round_budgets.py` — 5 tests

**Total: 5 collected** — 3 RED (xfail), 2 PASS (invariant pins).

## W8.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W8.2: …", strict=False)` | 4 RED pins below | W8.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

### Compatibility pins (pass on baseline `fc0a8a65`)

| Test | Why it is green today |
|------|------------------------|
| `test_existing_construction_sites_still_work_without_collateral` | RC11 — `Finding` has no `collateral` field yet; construction without it still works |

## Contract → test matrix (W8.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| RC11 — optional `Finding.collateral` list | W8.2a · `REVIEW-CHECKS.md` §5 | Unit | `test_finding_carries_optional_collateral_list` |
| RC11 — existing sites unchanged | W8 definition | Unit (compat) | `test_existing_construction_sites_still_work_without_collateral` |
| RC11 — Major+ must name collateral | W8.2b prompt contract | Unit | `test_major_findings_are_asked_to_name_collateral` |
| RC11 — Minor/Trivial exempt | W8.2b · do not inflate small findings | Unit | `test_collateral_is_not_required_for_minor_or_trivial` |
| RC11 — collateral bound by §6 evidence | `REVIEW-CHECKS.md` §6 | Unit | `test_collateral_claims_are_subject_to_the_evidence_rule` |

## Named symbols this suite pins (post-W8.2)

| Symbol | Module | Test |
|--------|--------|------|
| `Finding.collateral` | `analyzers/finding.py` | collateral list + compat tests |
| Review step 6 collateral clause | `modes/Review.py` | `test_major_findings_are_asked_to_name_collateral` |
| IncrementalReview step 8 collateral clause | `modes/IncrementalReview.py` | all `test_collateral_prompt` tests |
| Collateral inline rendering | `modes/_pr_summary_format.py` | (W8.2c — not pinned in W8.1) |

## Collection target (W8.1)

`tests/analyzers/test_finding_collateral.py` — 2 tests
`tests/modes/test_collateral_prompt.py` — 3 tests

**Total: 5 collected** — 4 RED (xfail), 1 PASS (RC11 compatibility pin).

## W7.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W7.2: …", strict=False)` | 8 RED pins below | W7.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

## Contract → test matrix (W7.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| RC10 — `AgentRole.recall` read-only tool surface | W7.2a · `REVIEWER_ALLOWED_TOOL_CLASSES` | Unit | `test_recall_role_is_registered_with_read_only_tool_classes` |
| RC10 — recall receives diff + draft list | W7.2b prompt contract | Unit | `test_recall_pass_receives_the_draft_finding_list` |
| RC10 — output excludes already-drafted findings | W7.2b · `findings/dedup.py` | Unit | `test_recall_pass_output_excludes_findings_already_drafted` |
| D1 — recall output always deferred | Decisions D1 | Integration | `test_recall_findings_land_in_the_deferred_lane_regardless_of_claimed_severity` |
| D7 — `review.recallPass` default off, on in this repo | Decisions D7 | Unit | `test_recall_pass_is_off_by_default_and_on_in_this_repo_config` |
| Subagent budget + timeout | W7.2a registry | Unit | `test_recall_pass_respects_the_subagent_budget_and_timeout` |
| Reviewer-shaped deny list (no terminal / mutation) | W7.2c | Integration | `test_recall_pass_cannot_call_terminal_or_mutation_tools` |
| W7 gate — recall up, DG1 precision flat | W7 acceptance · DG1 corpus | E2E | `test_recall_pass_raises_first_pass_recall_on_the_corpus` |

## Named symbols this suite pins (post-W7.2)

| Symbol | Module | Test |
|--------|--------|------|
| `AgentRole.recall` | `agents/registry.py` | registry + budget tests |
| `RECALL_SYSTEM_PROMPT` | `agents/recall.py` | draft brief test |
| `build_recall_pass_brief` | `agents/recall.py` | draft brief test |
| `filter_novel_recall_findings` | `agents/recall.py` | dedup test (must call `dedupe_findings`) |
| `place_recall_findings` | `agents/recall.py` | D1 deferred placement test |
| `plan_recall_pass` | `agents/recall.py` | budget / timeout test |
| `recall_denied_tool_names` | `agents/recall.py` | containment test |
| `review.recall_pass` | `config/settings.py` | D7 config test |
| `RECALL_PASS_W0_BASELINE` | `evals/convergence.py` | corpus gate test |
| `evaluate_recall_pass_corpus` | `evals/convergence.py` | corpus gate test |

## Collection target (W7.1)

`tests/agents/test_recall_pass.py` — 7 tests
`tests/evals/test_convergence.py` — 1 test (`test_recall_pass_raises_first_pass_recall_on_the_corpus`)

**Total: 8 collected** — 8 RED (xfail).

## W6.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W6.2: …", strict=False)` | 8 RED pins below | W6.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

## Contract → test matrix (W6.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| RC9 — promote deferred when region changes | W6.2a · W3 ledger | Integration | `test_deferred_finding_is_promoted_when_its_region_changes` |
| RC9 — untouched deferred stays deferred | W6.2a | Integration | `test_deferred_finding_in_an_untouched_region_stays_deferred` |
| Convention 5 — promotion keeps fingerprint | Global convention 5 | Unit | `test_promoted_finding_is_not_rediscovered_from_scratch` |
| RC9 — complement prefers lenses not run last round | W6.2b · W5 metadata | Unit | `test_lenses_that_did_not_run_last_round_are_preferred` |
| RC9 — complement cost guard | W6.2b | Unit | `test_complement_routing_does_not_rerun_every_lens_every_round` |
| D10 — label misses on pre-existing lines | Decisions D10 | Unit | `test_finding_on_pre_existing_line_is_labelled_a_first_pass_miss` |
| D10 — added lines are not misses | W6 definition | Unit | `test_finding_on_a_line_the_fix_added_is_not_labelled_a_miss` |
| D10 — exact miss label wording | Decisions D10 | Unit | `test_miss_label_wording_matches_the_pinned_string` |

## Named symbols this suite pins (post-W6.2)

| Symbol | Module | Test |
|--------|--------|------|
| `promote_deferred_for_incremental_paths` | `modes/_incremental_promotion.py` | promotion tests |
| `route_lenses_complement` | `review/lens_routing.py` | complement tests |
| `parse_dispatched_lenses_from_review_body` | `modes/_pr_summary_format.py` | complement cost-guard test |
| `FIRST_PASS_MISS_LABEL` | `modes/_incremental_miss.py` | miss wording test |
| `is_first_pass_miss_line` | `modes/_incremental_miss.py` | miss classification tests |
| `apply_first_pass_miss_label` | `modes/_incremental_miss.py` | miss labelling tests |
| `FindingLedger.promote` | `findings/ledger.py` | promotion audit (reuses W3) |

## D10 pinned string (W6.1)

Executors must copy verbatim into `IncrementalReview.py` step 8/9 and `FIRST_PASS_MISS_LABEL` in `modes/_incremental_miss.py`:

```text
_(First-pass miss — this line was already present at the first reviewed commit.)_
```

## Collection target (W6.1)

`tests/modes/test_incremental_promotion.py` — 3 tests
`tests/modes/test_incremental_complement.py` — 2 tests
`tests/modes/test_incremental_miss_labelling.py` — 3 tests

**Total: 8 collected** — 8 RED (xfail).

## W5.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W5.2: …", strict=False)` | 6 RED pins below | W5.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

### Compatibility pins (pass on baseline `fc0a8a65`)

| Test | Why it is green today |
|------|------------------------|
| `test_existing_finding_construction_sites_still_work_without_lens` | D9 — `Finding` has no `lens` field yet; construction without it still works |

## Contract → test matrix (W5.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| RC7 — routing decision on `ToolState` | W5.2a | Unit | `test_routing_decision_is_written_to_tool_state` |
| RC7 — dispatched ≠ recommended | W5 definition | Unit | `test_dispatched_lens_ids_are_recorded_not_just_recommended` |
| RC7 — skipped lenses + reasons | `REVIEW-CHECKS.md` §1 | Unit | `test_skipped_lenses_and_reasons_are_recorded` |
| RC7 — lens set survives to next round | W5.2c | Integration | `test_lens_set_is_serialized_into_review_metadata` |
| RC8 / D9 — optional `Finding.lens` | Decisions D9 | Unit | `test_finding_carries_optional_lens_attribution` |
| D9 — existing sites unchanged | Decisions D9 | Unit (compat) | `test_existing_finding_construction_sites_still_work_without_lens` |
| X1 — span `lens=` is lens id | W5.2e | Static | `test_agent_span_lens_attribute_is_a_lens_id_not_the_mode` |

## Named symbols this suite pins (post-W5.2)

| Symbol | Module | Test |
|--------|--------|------|
| `ToolState.lens_routing_decision` | `mcp/tool_state.py` | routing + skipped-lens tests |
| `ToolState.dispatched_lens_ids` | `mcp/tool_state.py` | dispatched ≠ recommended test |
| `record_lens_execution` | `mcp/tool_state.py` | all `test_lens_recording` tests |
| `merge_dispatched_lenses_into_review_metadata` | `modes/_pr_summary_format.py` | metadata round-trip test |
| `parse_dispatched_lenses_from_review_body` | `modes/_pr_summary_format.py` | metadata round-trip test |
| `Finding.lens` | `analyzers/finding.py` | lens attribution tests |
| `agent_run_span(..., lens=…)` | `main.py` (both call sites) | `test_lens_span` |

## Collection target (W5.1)

`tests/review/test_lens_recording.py` — 4 tests
`tests/analyzers/test_finding_lens_field.py` — 2 tests
`tests/tracing/test_lens_span.py` — 1 test

**Total: 7 collected** — 6 RED (xfail), 1 PASS (D9 compatibility pin).

## W4.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W4.2: …", strict=False)` | 6 RED pins below | W4.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

## Contract → test matrix (W4.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| Ground truth = deduped union by fingerprint | W4 definition | Unit | `test_ground_truth_is_the_deduped_union_across_rounds` |
| Post-fix findings excluded from round-one denominator | W4 attribution | Unit | `test_finding_about_code_added_by_the_fix_is_excluded_from_round_one_ground_truth` |
| Deferred counts as surfaced for recall | D1 / W4 definition | Unit | `test_first_pass_recall_counts_deferred_findings_as_surfaced` |
| Leakage zero when nothing discarded | W4 leakage rate | Unit | `test_leakage_rate_is_zero_when_nothing_is_discarded` |
| Recall uses `score_findings` ±3-line overlap | `evals/scoring.py` | Unit | `test_recall_uses_the_existing_location_overlap_rule` |
| Metric computable without live GitHub | RC6 / D4 | Integration | `test_metric_is_computable_from_the_ledger_alone` |

## Named symbols this suite pins (post-W4.2)

| Symbol | Module | Test |
|--------|--------|------|
| `ConvergenceRound` | `evals/convergence.py` | all convergence tests |
| `ConvergenceReport` | `evals/convergence.py` | recall / leakage / ground-truth tests |
| `score_convergence` | `evals/convergence.py` | all convergence tests |
| `ground_truth_fingerprints` | `ConvergenceReport` | dedup union test |
| `round_one_attributable_fingerprints` | `ConvergenceReport` | post-fix exclusion test |
| `ground_truth_attributable_to_round1` | `ConvergenceReport` | recall denominator |
| `first_pass_recall` | `ConvergenceReport` | deferred + overlap tests |
| `leakage_rate` | `ConvergenceReport` | leakage + ledger-only tests |
| `round_one_generated` / `round_one_surfaced` | `ConvergenceReport` | leakage test |
| `DEFAULT_LINE_SLACK` reuse | `evals/scoring.py` | overlap rule test |

## Collection target (W4.1)

`tests/evals/test_convergence.py` — 6 tests

**Total: 6 collected** — 6 RED (xfail).

## W3.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W3.2: …", strict=False)` | 9 RED pins below | W3.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

## Contract → test matrix (W3.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| Published / deferred / dropped all recorded | RC4 / RC5 | Unit | `test_published_deferred_and_dropped_findings_all_enter_the_ledger` |
| Ledger key = taxonomy fingerprint | Convention 5 | Unit | `test_ledger_key_is_the_review_taxonomy_fingerprint` |
| D4 — HTML block in sticky progress comment | Decisions D4 | Integration | `test_ledger_round_trips_through_the_sticky_comment_html_block` |
| Fresh checkout reads ledger from comment | RC4 | Integration | `test_ledger_survives_a_second_action_run_with_no_local_state` |
| W2 `skipped_over_budget` feeds ledger | RC4 / W2.2d | Unit | `test_ledger_records_over_budget_verifications_from_w2` |
| D5 — ledger never files issues | `docs/findings-carryover.md` | Unit | `test_ledger_never_files_a_github_issue` |
| D6 — extend `LifecycleState` Literal | Decisions D6 | Unit | `test_deferred_state_is_added_to_lifecycle_state_literal` |
| Convention 4 — promotion audit trail | Global convention 4 | Unit | `test_promotion_records_a_reason_and_timestamp` |
| CLI `findings ledger` read-only | W3.2e | Functional | `test_ledger_command_is_read_only` |

## Named symbols this suite pins (post-W3.2)

| Symbol | Module | Test |
|--------|--------|------|
| `LEDGER_MARKER_PREFIX` | `findings/ledger.py` | fingerprint + round-trip tests |
| `FindingLedger` | `findings/ledger.py` | all ledger unit tests |
| `merge_ledger_into_comment` | `findings/ledger.py` | sticky comment round-trip |
| `FindingLedger.from_comment_body` | `findings/ledger.py` | fresh-checkout survival |
| `record_over_budget_verifications` | `findings/ledger.py` | over-budget feed test |
| `files_github_issues` | `findings/ledger.py` | D5 guard |
| `LifecycleState` + `deferred` / `unpublished` | `findings/lifecycle.py` | D6 literal test |
| `LifecycleRecord.recorded_at` | `findings/lifecycle.py` | promotion audit trail |
| `findings ledger` CLI verb | `cli/findings_cmd.py` | CLI read-only test |

## Collection target (W3.1)

`tests/findings/test_ledger.py` — 8 tests
`tests/cli/test_findings_ledger_cmd.py` — 1 test

**Total: 9 collected** — 9 RED (xfail).

## W2.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W2.2: …", strict=False)` | 5 RED pins below | W2.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

### Compatibility pins (pass on baseline `fc0a8a65`)

| Test | Why it is green today |
|------|------------------------|
| `test_publication_still_caps_inline_at_eight` | D1 invariant — `default_inline_budget()` / `place_findings` inline cap stays 8 |
| `test_unverified_critical_is_still_gated` | D11 invariant — `filter_for_review` still gates unverified Critical/Major |

## Contract → test matrix (W2.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| D2 — `review.verificationBudget` default 24 | Decisions D2 | Unit | `test_verification_budget_defaults_to_twenty_four` |
| D2 — `0` means verify every eligible finding | Decisions D2 | Unit | `test_verification_budget_zero_means_no_cap` |
| RC3 — ninth Critical still verified | `agents/verifier.py` | Unit | `test_ninth_critical_finding_is_still_verified` |
| D1 — inline cap stays 8 | Global convention 3 | Unit (invariant) | `test_publication_still_caps_inline_at_eight` |
| Filter order severity → withdrawn → budget | `verifier.py:275-282` | Unit | `test_withdrawn_and_below_severity_filters_run_before_the_budget` |
| Over-budget fingerprints recorded (W3 feed) | RC4 / W2.2d | Unit | `test_over_budget_verifications_are_recorded_not_silently_dropped` |
| D11 gate unchanged | `review_gate.py:11-27` | Unit (invariant) | `test_unverified_critical_is_still_gated` |

## Collection target (W2.1)

`tests/agents/test_verifier_budget.py` — 6 tests
`tests/analyzers/test_review_gate.py` — 1 test

**Total: 7 collected** — 5 RED (xfail), 2 PASS (invariant pins).

## W1.1 xfail schedule

| Marker | Tests | Green after |
|--------|-------|-------------|
| `@pytest.mark.xfail(reason="green after W1", strict=False)` | 8 RED pins below | W1.2 implementation |

Never `strict=True` — impl waves must not touch `tests/`.

### Compatibility pins (pass on baseline `fc0a8a65`)

| Test | Why it is green today |
|------|------------------------|
| `test_inline_budget_is_still_eight` | D1 invariant — `default_inline_budget()` is already 8 |
| `test_no_inline_comment_is_created_for_a_deferred_finding` | D1 invariant — publish path never auto-inlines overflow; deferred path stays out of `comments` |

## Contract → test matrix (W1.1)

| Contract | Doc / decision | Layer | Test |
|----------|----------------|-------|------|
| RC1 — overflow agent findings keep body | `docs/ANALYZERS.md` D14 | Unit | `test_overflowed_agent_finding_keeps_its_body` |
| Deferred section renders severity, path, body | `REVIEW-CHECKS.md` §5 | Unit | `test_deferred_section_renders_severity_path_and_body` |
| Analyzer overflow stays compact tool table | `docs/ANALYZERS.md` D14 | Unit | `test_analyzer_overflow_still_renders_as_a_compact_tool_table` |
| D1 — inline budget stays 8 | Global convention 3 | Unit (invariant) | `test_inline_budget_is_still_eight` |
| Trivial / Low value never deferred | `REVIEW-CHECKS.md` §5 | Unit | `test_trivial_and_low_value_never_reach_the_deferred_section` |
| RC2 / D3 — publish appends deferred section | `modes/_pr_summary_format.py` | Integration | `test_publish_appends_deferred_section_without_agent_action` |
| Deferred section collapsed + non-blocking | User-visible surface | Integration | `test_deferred_section_is_collapsed_and_marked_non_blocking` |
| D1 — no inline comment for deferred | Global convention 3 | Integration (invariant) | `test_no_inline_comment_is_created_for_a_deferred_finding` |
| Convention 5 — fingerprint stamped | Global convention 5 | Integration | `test_deferred_findings_are_fingerprint_stamped` |
| X3 Fix-all reconciliation | `modes/_pr_summary_format.py` part 6 | Integration | `test_deferred_findings_appear_in_the_fix_all_brief_under_their_own_heading` |

## Named symbols this suite pins (post-W1.2)

| Symbol | Module | Test |
|--------|--------|------|
| `FindingPlacement.deferred` | `analyzers/budget.py` | budget deferred placement tests |
| `FindingPlacement.deferred_section` | `analyzers/budget.py` | budget deferred render tests |
| `_render_deferred_section` | `analyzers/budget.py` | `test_deferred_section_renders_severity_path_and_body` |
| `AnalyzerRunState.deferred_section` | `mcp/tool_state.py` | MCP publish tests |
| `_publish_github_review` deferred append | `mcp/review.py` | MCP publish tests |
| `DEFERRED_SECTION_HEADING` | `analyzers/budget.py` (expected) | `### 🗂 Deferred findings` |
| Fix-all `## Deferred (non-blocking)` | `modes/_pr_summary_format.py` | fix-all brief test |

## Collection target

`tests/analyzers/test_budget_deferred.py` — 5 tests
`tests/mcp/test_review_deferred_append.py` — 5 tests

**Total: 10 collected** — 8 RED (xfail), 2 PASS (invariant pins).
