# Review skill doctrine — test plan

Wave plan: `.ignorelocal/waves/21-review-skill-doctrine-wave-plan.md`
Worktree: `mc-review-skill` @ `wave/review-skill-doctrine`
Authoring wave: **RS1** (`test-creator`). Implementation: **RS2–RS4**.

## Contract matrix

| Contract | Greening wave | Primary test(s) |
| --- | --- | --- |
| **RS1.1** reference body lands in prompt | RS2 | `test_review_skill_references.py::test_review_skill_references_are_resolved_into_the_prompt` |
| **RS1.1** one-level reference depth (R4) | RS2 | `…::test_reference_resolution_is_one_level_deep` |
| **RS1.1** outside-skill links refused + recorded (D2/F3) | RS2 | `…::test_reference_outside_the_skill_directory_is_refused` |
| **RS1.1** absolute/traversal/symlink refused | RS2 | `…::test_absolute_and_traversal_paths_are_refused` |
| **RS1.1** per-reference byte cap | RS2 | `…::test_reference_resolution_respects_the_byte_cap` |
| **RS1.1** review-tier-only resolution (D4) | RS2 | `…::test_only_review_tier_skills_resolve_references` |
| **RS1.1** untrusted references stay fenced | RS2 | `…::test_untrusted_review_skill_references_render_inside_the_fence` |
| **RS1.1** missing reference recorded | RS2 | `…::test_missing_reference_is_a_recorded_limitation_not_a_silent_drop` |
| **RS1.2** total bundle byte cap (D5/G3) | RS2 | `test_instruction_bundle_budget.py::test_bundle_respects_the_total_byte_cap` |
| **RS1.2** truncation priority order | RS2 | `…::test_review_skill_and_references_survive_truncation_first` |
| **RS1.2** visible truncation limitation | RS2 | `…::test_truncation_is_reported_as_a_visible_limitation` |
| **RS1.2** exclude product skills (F6) | RS2 | `…::test_own_product_skills_are_excluded` |
| **RS1.2** skip agent config dirs (F7) | RS2 | `…::test_agent_config_dirs_are_skipped` |
| **RS1.2** skip nested worktrees (F7) | RS2 | `…::test_nested_worktree_is_skipped` |
| **RS1.2** empty repo renders nothing (guard) | RS2 | `…::test_a_repo_with_no_instruction_files_renders_nothing` |
| **RS1.3** record lists injected not discovered (D12/F5) | RS2 | `test_review_skill_record.py::test_record_lists_injected_skills_not_discovered_ones` |
| **RS1.3** record lists resolved references | RS2 | `…::test_record_lists_resolved_reference_files` |
| **RS1.3** quarantined skill recorded (F8) | RS2 | `…::test_quarantined_skill_is_recorded_as_quarantined` |
| **RS1.3** cap-dropped skill not applied | RS2 | `…::test_skill_discovered_but_dropped_by_the_cap_is_not_recorded_as_applied` |
| **RS1.4** empty external trace ≠ read coverage (F10) | RS2 | `test_trajectory_read_coverage.py::test_external_trace_with_no_reads_is_not_read_coverage` |
| **RS1.4** external trace with reads is coverage | RS2 | `…::test_external_trace_with_reads_is_read_coverage` |
| **RS1.4** MCP reads still coverage | RS2 | `…::test_mcp_observed_reads_are_still_read_coverage` |
| **RS1.5** Agent Skills frontmatter (D15/R2) | RS3/RS4 | `test_review_skill_spec.py::test_frontmatter_satisfies_the_agent_skills_spec` |
| **RS1.5** SKILL.md <500 lines (R3) | RS3 | `…::test_body_is_under_the_line_budget` |
| **RS1.5** references resolvable inside root | RS3 | `…::test_every_reference_link_resolves_and_is_inside_the_skill_root` |
| **RS1.5** no reference→reference links (R4) | RS3 | `…::test_no_reference_file_links_to_another_reference_file` |
| **RS1.5** long references carry TOC (R5) | RS3 | `…::test_reference_files_over_100_lines_open_with_a_table_of_contents` |
| **RS1.5** no literal `${{` in skill tree (D18) | RS4 | `…::test_skill_contains_no_literal_workflow_expression` |
| **RS1.5** taxonomy category drift gate (D8) | RS4 | `test_review_skill_taxonomy_drift.py::test_skill_names_every_finding_category` |
| **RS1.5** severity/effort/confidence drift gate | RS4 | `…::test_skill_names_every_severity_effort_and_confidence` |
| **RS1.5** blocking severity drift gate | RS4 | `…::test_skill_names_every_blocking_severity` |
| **RS1.5** withdrawn heading drift gate | RS4 | `…::test_skill_names_the_withdrawn_findings_heading` |
| **RS1.5** meta-test turns red on taxonomy add | RS4 | `…::test_gate_fails_when_a_taxonomy_value_is_added` |
| **RS1.6** E1 doctrine reaches reviewer (F1) | RS4 | `test_skill_eval_corpus.py::test_skill_eval_case_scores[skill-e1-doctrine-reaches-reviewer]` |
| **RS1.6** E2 repo trap action.yml (R16) | RS4 | `…[skill-e2-repo-trap-action-yml]` |
| **RS1.6** E3 abstention doc typo (D7) | RS4 | `…[skill-e3-abstention-doc-typo]` |
| **RS1.6** E4 withdrawn finding (D6) | RS4 | `…[skill-e4-withdrawn-finding]` |
| **RS1.6** corpus beats 366-byte baseline (D11) | RS4 | `…::test_skill_beats_its_baseline_on_the_corpus` |
| **RS1.7** CLI renders REVIEW SKILLS (F11) | RS2 | `test_offline_agent_review_context.py::test_cli_review_renders_the_review_skills_section` |
| **RS1.7** CLI populates `review_skills` extra | RS2 | `…::test_cli_review_populates_review_skill_paths` |
| **RS1.7** CLI resolves references | RS2 | `…::test_cli_review_resolves_skill_references` |
| **RS1.7** untrusted CLI fences skill (D19) | RS2 | `…::test_untrusted_cli_source_fences_the_discovered_skill` |
| **RS1.7** CLI respects bundle cap | RS2 | `…::test_cli_review_respects_the_bundle_cap` |
| **RS1.7** both offline call sites wired | RS2 | `…::test_both_call_sites_are_wired` |

## Deliverable symbols

| Symbol | Module (planned) | Test anchor |
| --- | --- | --- |
| `render_review_context` (+ `byte_cap`) | `context/instruction_discovery.py` | `test_instruction_bundle_budget.py`, `test_review_skill_references.py` |
| `build_review_skill_record` | `context/instruction_discovery.py` | `test_review_skill_record.py`, `test_review_skill_references.py` |
| `instruction_bundle_byte_cap` | `config/settings.py` | `test_instruction_bundle_budget.py` |
| `resolve_offline_review_trust_tier` wiring | `review/offline_agent.py` | `test_offline_agent_review_context.py` |
| `build_trajectory_record` read_coverage | `evidence/trajectory.py` | `test_trajectory_read_coverage.py` |
| `taxonomy_values_covered_by_skill` | `evals/skill_taxonomy_gate.py` | `test_review_skill_taxonomy_drift.py` |
| `score_skill_eval_case` / `evaluate_skill_eval_corpus` | `evals/skill.py` | `test_skill_eval_corpus.py` |
| Skill eval corpus JSON | `evals/cases/skill/*.json` | `test_skill_eval_corpus.py` |

## RS1 evidence

- Baseline prompt archive: `.ignorelocal/waves/evidence/rs0-baseline.txt` (`bytes: 92358`, `doctrine present: False`).
- RED scores archive: `.ignorelocal/waves/evidence/rs1-red.txt` (E1–E4 baseline scores at RS1 close-out).

## Escalation notes

- RS1 pins limitation/refusal markers as `instruction limitation` and `refused` substrings in the rendered bundle/record; RS2 may choose exact prose but must keep them visible and machine-checkable.
- The empty-repo guard (`test_a_repo_with_no_instruction_files_renders_nothing`) is intentionally **not** xfailed — it must stay green through RS2.
- RS1 fix pass (post-RS2): fixture repos call `repo.mkdir()` before pre-skill file writes; `test_only_review_tier_skills_resolve_references` links `references/checks.md` in the review-tier body; `resolve_offline_instructions` defaults `wired=True` (D19).
