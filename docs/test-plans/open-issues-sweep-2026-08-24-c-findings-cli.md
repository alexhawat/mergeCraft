# Open issues sweep 2026-08-24 lane C — CA #452 test plan

Maps **CA RED** contracts for #452 (stable short finding id) to the test suite.
Source plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-c-findings-cli-wave-plan.md`.

## D2 — short id derived from fingerprint → CA

| Contract | Tests | Layer |
| --- | --- | --- |
| Prefix is `MC-` | `tests/analyzers/test_finding_short_id.py::test_finding_short_id_prefix_is_mc` | unit |
| Same fingerprint → same short id | `…::test_finding_short_id_is_deterministic_for_same_fingerprint` | unit |
| Default truncation matches issue example (`MC-a83f91`) | `…::test_finding_short_id_uses_fingerprint_prefix` | unit |
| Different fingerprints → different ids | `…::test_finding_short_id_differs_for_different_fingerprints` | unit |
| Unsafe fingerprint rejected | `…::test_finding_short_id_rejects_unsafe_fingerprint[*]` | unit / error |
| Truncation collision disambiguated in batch | `…::test_resolve_finding_short_ids_disambiguates_truncation_collisions` | unit |
| Collision resolution is stable | `…::test_resolve_finding_short_ids_is_stable_for_repeated_calls` | unit |
| Markdown output includes short id | `tests/findings/test_finding_short_id_outputs.py::test_render_finding_markdown_includes_short_id` | integration |
| JSON record includes short id | `…::test_finding_json_record_includes_short_id_field` | integration |
| Agent JSONL record includes short id | `…::test_finding_agent_jsonl_record_includes_short_id_field` | integration |
| PR comment body includes short id | `…::test_render_finding_pr_comment_includes_short_id` | integration |
| Same `MC-…` across all surfaces | `…::test_all_output_surfaces_share_the_same_short_id` | functional |
| `mergecraft explain MC-…` resolves packet | `tests/cli/test_explain_short_id_cmd.py::test_explain_accepts_short_finding_id` | E2E |
| Unknown short id is an error | `…::test_explain_unknown_short_id_is_an_error` (no xfail — already fail-closed) | E2E / error |

## Pinned public API (implementation wave CA)

All symbols expected in `src/mergecraft/analyzers/finding.py`:

- `FINDING_SHORT_ID_PREFIX` — `"MC-"`
- `finding_short_id(fingerprint: str) -> str`
- `resolve_finding_short_ids(fingerprints: Sequence[str]) -> dict[str, str]`
- `render_finding_markdown(finding, *, short_id: str) -> str`
- `finding_json_record(finding, *, short_id: str) -> dict[str, Any]`
- `finding_agent_jsonl_record(finding, *, short_id: str) -> dict[str, Any]`
- `render_finding_pr_comment(finding, *, short_id: str) -> str`

`lookup_finding_packet` / `mergecraft explain` must accept the short id form.

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| CA | all tests in `tests/analyzers/test_finding_short_id.py`, `tests/findings/test_finding_short_id_outputs.py`, `tests/cli/test_explain_short_id_cmd.py` except `test_explain_unknown_short_id_is_an_error` |
| CA | ✅ reconciled 2026-08-24 — all 16 collected CA cases pass without `--runxfail` |

## CB #451 — Hunk exporter → CB RED

Source: D3, issue #451, `.ignorelocal/waves/hunk-spike-451-notes.md`.

| Contract | Tests | Layer |
| --- | --- | --- |
| Payload envelope `{"comments":[...]}` | `tests/findings/test_hunk_export.py::test_export_hunk_comments_returns_comments_envelope` | unit |
| Field map (`filePath`, `newLine`, `summary`, `rationale`, `author`) | `…::test_export_hunk_comment_maps_finding_fields_to_golden_shape` | unit |
| Never `hunkNumber` / `hunk` / `oldLine` fallback | `…::test_export_hunk_comment_never_emits_hunk_number_fallback` | unit / error |
| Default drop file-level (`start_line is None`) | `…::test_export_hunk_drops_file_level_findings_by_default` | unit |
| Opt-in `first-changed-line` + `[file-level]` prefix | `…::test_export_hunk_first_changed_line_maps_file_level_with_prefix` | unit / edge |
| Empty findings → `{"comments":[]}` | `…::test_export_hunk_empty_findings_returns_empty_comments` | edge |
| Author constant `mergeCraft` | `…::test_export_hunk_author_constant_is_mergecraft` | unit |
| Invalid `file_findings` rejected | `…::test_export_hunk_rejects_invalid_file_findings_mode` | error |
| Dropped count helper | `…::test_export_hunk_dropped_file_level_count_helper` | unit |
| Counted warning message copy | `…::test_export_hunk_file_level_warning_message_is_counted` | unit |
| Stdout-only JSON for piping | `tests/cli/test_diff_review_hunk_output.py::test_hunk_output_format_writes_json_to_stdout` | E2E |
| No `--output` required | `…::test_hunk_output_format_does_not_require_output_path` | E2E |
| Dropped file-level warning on stderr | `…::test_hunk_output_format_warns_about_dropped_file_level_on_stderr` | E2E |
| Structured findings wired (`json_path`) | `…::test_hunk_output_format_requests_structured_findings_from_run_offline` | integration |
| `--hunk-file-findings first-changed-line` | `…::test_hunk_file_findings_first_changed_line_flag` | E2E |
| Help documents `hunk` format | `…::test_review_help_lists_hunk_output_format` | functional |

### Pinned public API (implementation wave CB)

New module `src/mergecraft/findings/hunk_export.py`:

- `HUNK_COMMENT_AUTHOR` — `"mergeCraft"`
- `export_hunk_comments(findings, *, file_findings="drop", first_changed_lines=None) -> dict[str, Any]`
- `count_dropped_file_level_findings(findings) -> int`
- `format_file_level_drop_warning(count: int) -> str`

CLI (`src/mergecraft/cli/diff_review_cmd.py`):

- Extend `OutputFormat` with `"hunk"`
- `--hunk-file-findings {drop,first-changed-line}` (default `drop`)
- Hunk branch writes JSON to **stdout**; dropped-file-level warnings on **stderr**

## xfail reconciliation (CB)

| Wave greens | Remove xfail from |
| --- | --- |
| CB | all tests in `tests/findings/test_hunk_export.py`, `tests/cli/test_diff_review_hunk_output.py` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q \
  tests/analyzers/test_finding_short_id.py \
  tests/findings/test_finding_short_id_outputs.py \
  tests/cli/test_explain_short_id_cmd.py \
  tests/findings/test_hunk_export.py \
  tests/cli/test_diff_review_hunk_output.py
uv run pytest -q \
  tests/analyzers/test_finding_short_id.py \
  tests/findings/test_finding_short_id_outputs.py \
  tests/cli/test_explain_short_id_cmd.py
# CA passes; CB cases remain XFAIL until implementation lands
```
