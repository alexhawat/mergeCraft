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
| CB | ✅ reconciled 2026-08-24 — fixed duplicate-kwarg helpers in `tests/cli/test_diff_review_hunk_output.py`; 16/16 CB cases pass without `--runxfail` |

## CC #454 — Finding round-trip conformance → CC

Source: D5, issue #454 (after #451).

| Contract | Tests | Layer |
| --- | --- | --- |
| JSON record round-trips every corpus case | `tests/findings/test_finding_output_round_trip.py::test_json_record_round_trips_finding` | integration |
| Agent JSONL matches JSON projection | `…::test_agent_jsonl_record_matches_json_record` | integration |
| Markdown preserves core semantics | `…::test_markdown_render_preserves_core_semantics` | integration |
| PR comment preserves core semantics | `…::test_pr_comment_render_preserves_core_semantics` | integration |
| SARIF preserves message/rule/path/region | `…::test_sarif_export_preserves_core_semantics` | integration |
| Hunk default drop for file-level | `…::test_hunk_default_export_respects_file_level_drop` | unit / edge |
| Hunk first-changed-line named hack | `…::test_hunk_first_changed_line_exports_file_level_with_named_hack` | unit |
| Hunk never invents location fallbacks | `…::test_hunk_export_never_invents_location_fallbacks` | unit / error |
| Named hacks documented (D5) | `…::test_named_format_hacks_are_documented` | functional |
| Same short id across all surfaces | `…::test_all_formats_share_short_id_for_one_finding` | functional |
| JSON restore rejects `short_id` field | `…::test_json_round_trip_rejects_export_only_fields_on_restore` | error |

### Corpus (`tests/findings/support_round_trip.py`)

| Case id | Exercises |
| --- | --- |
| `line_anchored_minimal` | baseline line-anchored finding |
| `file_level` | `start_line is None` |
| `multi_line_range` | `start_line != end_line` with evidence |
| `empty_evidence` | `evidence=[]` |
| `no_remediation` | `remediation is None` |
| `full_metadata` | optional fields populated |
| `unicode_message` | non-ASCII path and message |

### Named format hacks (D5)

Declared in `tests/findings/support_round_trip.py::NAMED_FORMAT_HACKS`:

- `JSON_ADDS_SHORT_ID` / `AGENT_JSONL_ADDS_SHORT_ID`
- `MARKDOWN_ONE_WAY_RENDER` / `PR_COMMENT_ONE_WAY_RENDER`
- `HUNK_FILE_LEVEL_DROP` / `HUNK_FILE_LEVEL_FIRST_CHANGED_LINE`
- `SARIF_SEVERITY_TO_LEVEL` / `SARIF_FILE_LEVEL_NO_REGION`

## CD #453 — durable completed review by id → CD RED

Source: D4, issue #453. No `mergecraft/renderers/` package. No `mergecraft session *`.
Durable review composes `ReviewSnapshot` + run manifest + findings + evidence packets;
existing `explain` / `findings` / `replay` resolve by stored review id without re-running.

| Contract | Tests | Layer |
| --- | --- | --- |
| Persist stable review id | `tests/review/test_durable_review_completed.py::test_persist_completed_review_writes_stable_review_id` | unit |
| D4 composition on disk (snapshot + manifest + findings) | `…::test_persist_stores_snapshot_manifest_and_findings` | integration |
| Unknown review id is a miss | `…::test_load_returns_none_for_unknown_review_id` | error |
| Corrupt stored record is a miss | `…::test_load_returns_none_for_corrupt_completed_record` | error |
| List stored review ids | `…::test_list_completed_review_ids_returns_persisted_ids` | functional |
| Storage under `.mergecraft/reviews/<id>` | `…::test_completed_review_dir_lives_under_mergecraft_reviews` | unit |
| `CompletedReview` model round-trip | `…::test_completed_review_model_round_trips_required_fields` | unit |
| Review persists id on success | `tests/cli/test_durable_review_by_id_cmd.py::test_review_persists_completed_review_id_on_success` | E2E |
| `findings <review-id>` without rerun | `…::test_findings_by_review_id_returns_stored_findings_without_rerun` | E2E |
| `explain <review-id> MC-…` resolves packet | `…::test_explain_with_review_id_and_short_finding_id_resolves_packet` | E2E |
| `explain MC-… --review-id` resolves packet | `…::test_explain_short_id_with_review_context_flag_resolves_packet` | E2E |
| `replay <review-id>` from stored traces | `…::test_replay_by_review_id_uses_stored_artifacts_without_rerun` | E2E |
| Unknown review id fail-closed | `…::test_unknown_review_id_is_fail_closed_for_findings` | E2E / error |
| Lookup never invokes review agent | `…::test_findings_lookup_does_not_invoke_review_agent` | functional |

### Pinned public API (implementation wave CD)

New module `src/mergecraft/review/completed.py`:

- `COMPLETED_REVIEW_SCHEMA_VERSION` — `"1.0.0"`
- `CompletedReview` — frozen record with `review_id`, `snapshot`, `manifest`, `findings`, `trace_session_id`
- `completed_review_dir(review_id, *, repo_root) -> Path`
- `persist_completed_review(review, *, repo_root, evidence_packets=None, trace_events=None) -> Path`
- `load_completed_review(review_id, *, repo_root) -> CompletedReview | None`
- `list_completed_review_ids(*, repo_root) -> list[str]`

On-disk layout under `<repo>/.mergecraft/reviews/<review_id>/`:

- `snapshot.json`, `manifest.json`, `findings.json`, `completed.json`
- evidence packets + `trace.jsonl` co-located for `explain` / `replay`

CLI extensions (compose existing verbs — no `session` namespace):

- `mergecraft review` JSON output includes `review_id` and persists on success
- `mergecraft findings <review-id> [--repo-root PATH]`
- `mergecraft explain <review-id> <MC-…>` and `mergecraft explain <MC-…> --review-id <id>`
- `mergecraft replay <review-id> [--repo-root PATH]`

## xfail reconciliation (CD)

| Wave greens | Remove xfail from |
| --- | --- |
| CD | all tests in `tests/review/test_durable_review_completed.py`, `tests/cli/test_durable_review_by_id_cmd.py` |
| CD | ✅ reconciled 2026-08-24 — 14/14 CD cases pass without `--runxfail` |

## CE #455 — per-lens routing capability numbers → CE RED

Source: D6, issue #455. Additive eval metrics only — do not rebuild the eval
harness. Output must be diffable across commits (sorted JSON + content digest).

| Contract | Tests | Layer |
| --- | --- | --- |
| Per-lens TP/FP/FN → precision/recall | `tests/evals/test_lens_routing_capability.py::test_score_lens_routing_reports_per_lens_precision_and_recall` | unit |
| Macro averages over participating lenses | `…::test_score_lens_routing_macro_averages_participating_lenses_only` | unit |
| Expected-but-never-selected → recall only | `…::test_lens_never_selected_has_no_precision_but_can_have_recall` | edge |
| Spurious selection → precision only | `…::test_lens_selected_but_never_expected_has_no_recall` | edge |
| Empty corpus honest-zero macros | `…::test_empty_corpus_yields_honest_zero_macro_metrics` | edge |
| Mismatched case ids rejected | `…::test_score_lens_routing_rejects_mismatched_case_ids` | error |
| Schema version pinned | `…::test_lens_routing_capability_report_pins_schema_version` | unit |
| Canonical sorted JSON | `tests/evals/test_lens_capability_json.py::test_render_lens_capability_json_is_canonical_and_sorted` | functional |
| Stable content digest | `…::test_lens_capability_digest_is_stable_for_identical_reports` | functional |
| Digest ignores dict order | `…::test_lens_capability_digest_ignores_dict_insertion_order` | edge |

### Pinned public API (implementation wave CE)

New module `src/mergecraft/evals/lens_capability.py`:

- `LENS_CAPABILITY_SCHEMA_VERSION` — `"1.0.0"`
- `LensRoutingCaseLabel` — `case_id`, `expected_lens_ids`
- `LensRoutingCaseOutcome` — `case_id`, `selected_lens_ids`
- `PerLensRoutingMetrics` — `lens_id`, `precision`, `recall`, `true_positives`, `false_positives`, `false_negatives`
- `LensRoutingCapabilityReport` — `schema_version`, `cases`, `by_lens`, `macro_precision`, `macro_recall`, `macro_f1`
- `score_lens_routing(labels, outcomes) -> LensRoutingCapabilityReport`
- `render_lens_capability_json(report) -> str` — compact JSON, `sort_keys=True`
- `lens_capability_digest(report) -> str` — SHA-256 over canonical JSON

## xfail reconciliation (CE)

| Wave greens | Remove xfail from |
| --- | --- |
| CE | all tests in `tests/evals/test_lens_routing_capability.py`, `tests/evals/test_lens_capability_json.py` |
| CE | ✅ reconciled 2026-08-24 — 10/10 CE cases pass without `--runxfail` |

## CF #473 — `mergecraft update` + commit in `--version` → CF RED

Source: D7, issue #473. ``update`` shells to ``uv tool install --reinstall``;
default ref ``main``; ``--branch`` accepts branch/tag/SHA. Version text shows
``0.1.0a1 (abc1234)`` when commit known; omit parens when unknown. JSON ``commit``
field is additive on ``version --format json``.

| Contract | Tests | Layer |
| --- | --- | --- |
| ``update --help`` documents uv reinstall | `tests/cli/test_update_version_cmd.py::test_update_help_documents_uv_reinstall` | functional |
| Default update uses ``main`` ref | `…::test_update_default_shells_to_uv_tool_install_on_main` | E2E |
| ``--branch`` accepts branch/tag/SHA | `…::test_update_branch_option_accepts_branch_tag_or_sha[*]` | E2E / edge |
| Version helper with known commit | `…::test_format_version_display_includes_short_commit_when_known` | unit |
| Version helper without commit | `…::test_format_version_display_omits_paren_commit_when_unknown` | unit |
| ``--version`` with commit | `…::test_version_flag_includes_commit_when_known` | E2E |
| ``version`` with commit | `…::test_version_command_includes_commit_when_known` | E2E |
| ``--version`` without commit parens | `…::test_version_flag_omits_paren_commit_when_unknown` | edge |
| JSON ``commit`` field additive | `…::test_version_json_includes_additive_commit_field` | functional |
| JSON ``commit`` null when unknown | `…::test_version_json_commit_null_when_unknown` | edge |
| ``uv`` failure propagates | `…::test_update_run_uses_check_true` | error |

### Pinned public API (implementation wave CF)

New module `src/mergecraft/cli/update_cmd.py`:

- `DEFAULT_UPDATE_REF` — `"main"`
- `MERGECRAFT_GIT_ORIGIN` — `"https://github.com/alexhawat/mergeCraft"`
- `build_uv_install_argv(ref: str) -> list[str]` — argv for ``uv tool install --reinstall …``
- `run(*, branch: str | None = None) -> None` — Typer command entry

`src/mergecraft/__init__.py`:

- `__commit__` — optional full build commit SHA (``None`` when unknown)

Version helpers (module TBD — likely `mergecraft.version` or `cli/app.py`):

- `format_version_display(version: str, commit: str | None) -> str`
- `version_json_payload(version: str, commit: str | None) -> dict[str, Any]` — includes
  ``schema_version``, ``version``, additive ``commit`` (short SHA or ``None``)

CLI (`src/mergecraft/cli/app.py`):

- `app.add_typer(update_cmd.app, name="update")` or `app.command("update")`
- Root ``--version`` and ``version`` use ``format_version_display``
- ``version --format json`` emits ``version_json_payload``

## xfail reconciliation (CF)

| Wave greens | Remove xfail from |
| --- | --- |
| CF | all tests in `tests/cli/test_update_version_cmd.py` |
| CF | ✅ reconciled 2026-08-24 — 13/13 CF cases pass without `--runxfail` |

## CG #465 — review timeout budget composition → CG RED

Source: D8, issue #465. One declared per-attempt budget; job
``timeout-minutes`` must exceed the sum of sequential review attempts plus
checkout/setup slack. Do **not** shorten per-attempt timeouts to make room for
Codex fallback — retries do not accumulate progress.

| Contract | Tests | Layer |
| --- | --- | --- |
| Single declared attempt budget env | `tests/ci/test_mergecraft_workflow_timeout_budget.py::test_workflow_declares_single_review_attempt_timeout_budget` | unit |
| Nous + Codex steps derive ``with.timeout`` | `…::test_mergecraft_review_steps_reference_declared_attempt_timeout` | integration |
| Job budget > 2× attempt + slack | `…::test_review_job_timeout_composes_from_attempt_budget` | functional |
| Full budget per attempt (not shortened) | `…::test_per_attempt_timeout_not_shortened_below_declared_budget` | edge |

### Pinned public contract (implementation wave CG)

Workflow (``.github/workflows/mergecraft.yml`` only — lane C scope):

- ``env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES`` — single declared per-attempt
  budget (whole minutes)
- Both ``alexhawat/mergeCraft`` review steps use
  ``timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m`` (or
  equivalent env wiring — no independent ``25m`` literals)
- ``review`` job ``timeout-minutes`` strictly greater than
  ``2 × attempt + CHECKOUT_AND_SETUP_SLACK`` (10 minutes per
  ``tests/ci/support_review_timeout_budget.py``)

Helpers under ``tests/ci/support_review_timeout_budget.py`` encode the
composition rule for pytest; implementation may mirror the same constants in
workflow comments.

Observability (D8): promote enough agent logs that a 25m stall is diagnosable —
**out of lane C YAML scope**; tracked separately from these workflow-timeout
tests.

## xfail reconciliation (CG)

| Wave greens | Remove xfail from |
| --- | --- |
| CG | all tests in `tests/ci/test_mergecraft_workflow_timeout_budget.py` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q \
  tests/analyzers/test_finding_short_id.py \
  tests/findings/test_finding_short_id_outputs.py \
  tests/cli/test_explain_short_id_cmd.py \
  tests/findings/test_hunk_export.py \
  tests/cli/test_diff_review_hunk_output.py \
  tests/findings/test_finding_output_round_trip.py \
  tests/review/test_durable_review_completed.py \
  tests/cli/test_durable_review_by_id_cmd.py \
  tests/evals/test_lens_routing_capability.py \
  tests/evals/test_lens_capability_json.py \
  tests/cli/test_update_version_cmd.py \
  tests/ci/test_mergecraft_workflow_timeout_budget.py
uv run pytest -q \
  tests/analyzers/test_finding_short_id.py \
  tests/findings/test_finding_short_id_outputs.py \
  tests/cli/test_explain_short_id_cmd.py \
  tests/findings/test_hunk_export.py \
  tests/cli/test_diff_review_hunk_output.py \
  tests/findings/test_finding_output_round_trip.py \
  tests/review/test_durable_review_completed.py \
  tests/cli/test_durable_review_by_id_cmd.py \
  tests/evals/test_lens_routing_capability.py \
  tests/evals/test_lens_capability_json.py \
  tests/cli/test_update_version_cmd.py \
  tests/ci/test_mergecraft_workflow_timeout_budget.py
```
