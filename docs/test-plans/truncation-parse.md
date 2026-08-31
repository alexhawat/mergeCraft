# Truncation & parse hardening — test plan (TP1)

Wave plan: `.ignorelocal/waves/truncation-parse-wave-plan.md`
Worktree: `../mergecraft-truncation-parse` @ `wave/truncation-parse`
Authoring wave: **TP1** (tests-first). Implementation: **TP2–TP5**.

Locked decisions applied: **D2** (test-creator owns `tests/`), **D3–D8** (client pagination),
**D9** (TruffleHog JSONL skip), **D10** (SARIF 2.1.0 only), **D11** (overflow line clamp).

## xfail schedule

TP1 ships cross-wave `xfail(strict=False)` markers tagged `green after TPN`. Impl waves
green them; **test-creator** reconciles satisfied markers after each impl wave.

| Greening wave | Test files |
| --- | --- |
| TP2 | `tests/utils/test_github_pagination.py` (xfail-marked B1 cases) |
| TP3 | `tests/analyzers/parsers/test_trufflehog_jsonl.py` (`test_truncated_first_line_…`) |
| TP4 | `tests/analyzers/parsers/test_sarif.py` (2.0.0 + missing `version`) |
| TP5 | `tests/analyzers/test_budget.py` (overflow line clamp cases) |

## Contract → coverage matrix

### TP1.1 — B1 GitHub list pagination (TP2)

| Test | Contract |
| --- | --- |
| `test_list_reviews_concatenates_three_pages_in_order` | 100+100+1 reviews → 201 items, ordered |
| `test_list_issue_comments_concatenates_three_pages_in_order` | Same for issue comments |
| `test_list_pull_files_concatenates_three_pages_in_order` | Same for pull files |
| `test_list_check_runs_for_ref_concatenates_three_pages_preserves_total_count` | Wrapped `check_runs`; first-page `total_count` preserved (D8); already green pre-TP2 |
| `test_list_workflow_run_artifacts_concatenates_three_pages` | Wrapped `artifacts` concatenation; already green pre-TP2 |
| `test_list_issues_with_page_param_issues_single_get` | `list_issues` stays single GET when caller passes `page=` (D6) |
| `test_list_reviews_stops_at_fifty_pages_and_logs_truncation_warning` | Page 51 not requested; warning names truncation (D5) |
| `test_last_reviewed_sha_returns_newest_mergecraft_review_from_page_three` | Newest mergeCraft review on page 3 → `commit_id`; guard-deletion via first-page-only |

### TP1.2 — B3 TruffleHog JSONL (TP3)

| Test | Contract |
| --- | --- |
| `test_truncated_first_line_plus_valid_detector_yields_one_finding` | Truncated line skipped; one finding; no raise (D9) |
| `test_empty_lines_are_skipped` | Blank lines ignored |
| `test_json_array_line_is_skipped_without_crash` | Non-dict JSON line skipped |

### TP1.3 — B7 SARIF version (TP4)

| Test | Contract |
| --- | --- |
| `test_sarif_2_0_0_with_nonempty_runs_raises_unsupported_version` | `2.0.0` + non-empty `runs` → `ValueError` / `unsupported SARIF version` (D10) |
| `test_sarif_2_1_0_with_same_runs_parses` | `2.1.0` + same `runs` parses |
| `test_sarif_2_1_0_with_empty_runs_returns_no_findings` | `2.1.0` + `runs: []` → `[]` |
| `test_sarif_missing_version_raises_unsupported_version` | Missing `version` → same error |

### TP1.4 — B2 overflow clamp (TP5)

| Test | Contract |
| --- | --- |
| `test_overflow_agent_line_zero_clamps_to_start_line_one` | `inline_budget=0`, `line: 0` → `start_line == 1`, no `FindingValidationError` (D11) |
| `test_overflow_agent_negative_line_clamps_to_one` | Negative `line` clamps to 1 |
| `test_overflow_agent_supplied_line_twelve_is_unchanged` | `line: 12` unchanged |
| `test_overflow_agent_invalid_severity_still_raises` | Bad severity still raises `FindingValidationError` |
