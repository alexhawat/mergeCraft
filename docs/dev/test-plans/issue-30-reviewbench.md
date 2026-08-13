# Issue #30 ReviewBench — Batch A test plan (W1 RED)

Wave plan: `.ignorelocal/waves/issue-30-reviewbench-wave-plan.md`
Worktree: `mergecraft-issue-30-reviewbench` @ `wave/issue-30-reviewbench`

## Locked decisions exercised

| ID | Decision | Tests |
|----|----------|-------|
| **D3** | Schema derived from `Finding.model_json_schema()` wrapped in `{"findings": [...]}` | `test_findings_output_schema_is_valid_json_schema` |
| **D4** | CLI flag name `--json PATH` | `test_cli_diff_review_help_lists_json`, CLI invoke paths in json tests |
| **D5** | Dual output (`--json` + `-o`) | Deferred to W3 impl / optional follow-on — not RED-scoped in W1 |
| **D6** | `--json` requires structured `set_output`; validate each item as `Finding`; fail if missing output | `test_cli_diff_review_json_validates_findings`, prompt requirement test |
| **D7** | `--dry-run --json` writes nothing; exit 0 | `test_cli_diff_review_json_dry_run_does_not_write_file` |

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W2** | `tests/cli/test_diff_review_json.py::test_findings_output_schema_is_valid_json_schema` | `green after W2: findings_output_schema helper` |
| **W3** | `test_build_offline_review_prompt_requires_set_output_when_json_mode` | `green after W3: json_mode prompt requirement` |
| **W3** | `test_cli_diff_review_json_dry_run_does_not_write_file` | `green after W3: --json dry-run wiring` |
| **W3** | `test_cli_diff_review_json_validates_findings[valid_finding]` | `green after W3: --json validation wiring` |
| **W3** | `test_cli_diff_review_json_validates_findings[invalid_finding]` | `green after W3: --json validation wiring` |
| **W3** | `test_cli_diff_review_help_lists_json` | `green after W3: --json in help` |

All cross-wave markers use `strict=False`.

## Contract matrix

| Contract | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| D3 — derived JSON Schema | Unit | Happy — `properties.findings` array of `Finding` fields; `required: ["findings"]` | `test_findings_output_schema_is_valid_json_schema` |
| D6 — prompt requires `set_output` when JSON mode | Unit | Happy — step 4 says required, not “if available” | `test_build_offline_review_prompt_requires_set_output_when_json_mode` |
| D7 — dry-run + JSON | Functional | Happy — exit 0, JSON path not created | `test_cli_diff_review_json_dry_run_does_not_write_file` |
| D6 — validate findings on write | Integration | Happy — monkeypatched agent output → file round-trips `Finding.model_validate` | `test_cli_diff_review_json_validates_findings[valid_finding]` |
| D6 — invalid finding rejected | Integration | Error — malformed finding → non-zero exit | `test_cli_diff_review_json_validates_findings[invalid_finding]` |
| D4 — CLI surface documented | Functional | Happy — `--help` lists `--json` | `test_cli_diff_review_help_lists_json` |

## Implementation notes for impl waves

- **W2:** Add `findings_output_schema()` in `offline_review.py` or `utils/payload.py`; un-xfail schema test only.
- **W3:** Wire `--json`, `json_mode` on `build_offline_review_prompt`, MCP `output_schema`, post-run validation/write; un-xfail all W3 rows.
- **Existing suite:** `tests/cli/test_diff_review.py` must remain green unchanged (markdown default, dry-run without `--json`).

## Monkeypatch contract (W1.4)

`test_cli_diff_review_json_validates_findings` patches `mergecraft.offline_review._run_agent_review` to return JSON `{"findings": [...]}` without invoking a live agent. W3 should validate and write from structured agent output (`tool_state.output` or equivalent) before exit.
