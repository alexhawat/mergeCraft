# Test-suite honesty — T3 behavioural suites for the five untested modules

Scope: the five modules named by #768, each of which had shipped under a closed
feature issue with no behavioural test: `reliability/recovery.py`,
`pr/similar.py`, `requirements/ingest.py`, `prep/node.py`, and
`integrations/cursor_cloud/client.py` — plus the surviving `verdict_vocab`
gap on `EvalMetadata.expected_decision`.

Worktree: `../mc-honesty` on branch `wave/test-suite-honesty`.
Owner of `tests/` and this file: `test-creator`.

All tests are **green** against current product code; **no production file was
changed** (T-D9). No product bug was found, so no issue was filed and no xfail
was added. Every suite below asserts an observable outcome — a side effect, a
parsed result, a state, an error type *and* message, a call count — never
`callable(...)`, `hasattr(...)`, or the mere existence of a symbol (T-D8).

## Contract matrix

| Contract | Test node(s) |
| --- | --- |
| Cleanup delegates to the process-group kill helper for every named mode | `tests/reliability/test_recovery.py::test_cleanup_invokes_the_process_group_kill_for_every_mode` (5 modes) |
| Cleanup genuinely terminates a registered process group | `tests/reliability/test_recovery.py::test_cleanup_terminates_a_registered_process_group` |
| A cleanup that cannot complete fails loudly — no false `cleaned=True` | `tests/reliability/test_recovery.py::test_cleanup_failure_is_not_reported_as_cleaned` |
| Unknown mode is rejected before any process is signalled | `tests/reliability/test_recovery.py::test_unknown_mode_raises_before_signalling_anything` (5 values) |
| `cancellation` is the accepted vocabulary name, not `cancel` | `tests/reliability/test_recovery.py::test_cancellation_is_the_accepted_name_not_cancel` |
| `_overlap_score` is Jaccard: identity, disjoint, partial, empty sides | `tests/pr/test_similar.py::test_overlap_score_is_jaccard` (7 cases) |
| Score is symmetric | `tests/pr/test_similar.py::test_overlap_score_is_symmetric` |
| Tokenization casefolds and splits on non-alphanumerics | `tests/pr/test_similar.py::test_tokens_casefold_and_split_on_non_alphanumerics` |
| Issue matches rank by score; disjoint and blank-title rows drop | `tests/pr/test_similar.py::test_find_similar_issues_orders_by_score_and_drops_disjoint` |
| `limit` truncates, `limit=0` empties | `tests/pr/test_similar.py::test_find_similar_issues_respects_the_limit_boundary` |
| Non-integer candidate numbers become `None` | `tests/pr/test_similar.py::test_find_similar_issues_only_carries_integer_numbers` |
| Matching never mutates the caller's candidate mapping | `tests/pr/test_similar.py::test_find_similar_issues_does_not_mutate_candidates` |
| Change matches score by wanted-path coverage and drop disjoint rows | `tests/pr/test_similar.py::test_find_similar_changes_scores_by_wanted_overlap` |
| Empty wanted-path set lists every candidate at 0.0 | `tests/pr/test_similar.py::test_find_similar_changes_without_wanted_paths_lists_all_at_zero` |
| Malformed rows drop; title/sha coerce | `tests/pr/test_similar.py::test_find_similar_changes_drops_malformed_rows_and_coerces_fields` |
| `_git_change_candidates` parses a real fixture repo newest-first, with paths and full SHAs | `tests/pr/test_similar.py::test_git_change_candidates_reads_recent_commits_newest_first` |
| No `.git` (or a non-repo `.git`) yields an empty catalog | `tests/pr/test_similar.py::test_git_change_candidates_returns_empty_without_a_git_dir`, `…::test_git_change_candidates_returns_empty_when_git_dir_is_not_a_repo` |
| `repo_root` routes through the git catalog end-to-end | `tests/pr/test_similar.py::test_find_similar_changes_uses_git_candidates_when_repo_root_given` |
| Ingest returns stable ordered ids, source, and kinds | `tests/requirements/test_ingest.py::test_ingest_returns_stable_ordered_ids_and_kinds` |
| External text is nonce-fenced; every requirement carries the same fence | `tests/requirements/test_ingest.py::test_ingest_fences_external_text_with_one_shared_nonce` |
| Only bullets inside the acceptance section ingest | `tests/requirements/test_ingest.py::test_only_bullets_inside_the_acceptance_section_are_ingested` |
| Empty body yields no requirements and still fences | `tests/requirements/test_ingest.py::test_empty_body_yields_no_requirements_and_still_fences` |
| States from code evidence & scope: partially_satisfied / contradicted (negative) / out_of_scope | `tests/requirements/test_ingest.py::test_state_from_code_evidence_and_scope` (3 cases) |
| Test evidence → satisfied, with evidence paths | `tests/requirements/test_ingest.py::test_test_evidence_is_satisfied` |
| No change map → every requirement not_evidenced | `tests/requirements/test_ingest.py::test_without_a_change_map_every_requirement_is_not_evidenced` |
| Unknown source rejected with the locked message | `tests/requirements/test_ingest.py::test_unknown_source_is_rejected_before_any_extraction` |
| Named sources (incl. ticket aliases) accepted | `tests/requirements/test_ingest.py::test_named_sources_are_accepted` (6 sources) |
| Explicit text outranks `pr_description` | `tests/requirements/test_ingest.py::test_explicit_text_wins_over_pr_description` |
| `pr_description` / `linked_issue` fallbacks | `tests/requirements/test_ingest.py::test_pr_description_used_when_text_absent`, `…::test_linked_issue_used_when_text_absent` |
| Local spec discovery, candidate priority, ADR fallback, missing-file case | `tests/requirements/test_ingest.py::test_local_spec_reads_spec_md_from_repo_root`, `…::test_root_spec_md_wins_over_docs_spec`, `…::test_adr_falls_back_to_docs_adr`, `…::test_local_spec_without_files_yields_empty_requirements` |
| Node package-manager detection (field, devEngines, lockfile order, default) | `tests/prep/test_node.py::test_detect_package_manager` (13 cases) |
| Malformed `package.json` falls through to lockfiles | `tests/prep/test_node.py::test_malformed_package_json_falls_back_to_lockfile` |
| Install argv per manager, lockfile, and `--ignore-scripts` | `tests/prep/test_node.py::test_install_args` (8 cases) |
| Fail closed: scripts disabled + missing manager executes nothing and maps to inconclusive | `tests/prep/test_node.py::test_shell_disabled_missing_manager_refuses_to_run_anything` |
| Missing manager with shell enabled reports unavailable and executes nothing | `tests/prep/test_node.py::test_shell_enabled_missing_npm_reports_unavailable` |
| bun/deno provisioned via npm; corepack path for pnpm/yarn; failure output surfaced | `tests/prep/test_node.py::test_missing_bun_is_provisioned_via_npm`, `…::test_failed_provision_reports_manager_output`, `…::test_missing_pnpm_uses_corepack_when_available` |
| Frozen-lockfile install runs and succeeds; failures are fail-closed | `tests/prep/test_node.py::test_pnpm_install_uses_frozen_lockfile_and_ignore_scripts`, `…::test_failed_install_is_fail_closed`, `…::test_failed_install_without_output_names_the_exit_code`, `…::test_deno_install_succeeds` |
| Cursor API key env read + strip + empty | `tests/integrations/cursor_cloud/test_client.py::test_resolve_cursor_api_key_reads_and_strips_env` |
| Request sends basic auth and returns the parsed object | `…::test_request_sends_basic_auth_and_returns_object` |
| Non-2xx: detail, message, and full-body fallbacks | `…::test_permanent_4xx_raises_runtime_error_with_detail`, `…::test_error_uses_message_field_when_detail_absent`, `…::test_error_falls_back_to_the_full_body` |
| Non-JSON and non-object bodies rejected | `…::test_non_json_body_raises_runtime_error`, `…::test_non_object_json_raises_runtime_error` |
| Retry boundary: mutations never retry; reads retry to exhaustion | `…::test_mutation_5xx_is_not_retried`, `…::test_read_5xx_retries_to_exhaustion`, `…::test_mutation_transport_error_is_not_retried`, `…::test_read_timeout_retries_to_exhaustion` |
| `create_cloud_agent` payload shaping, defaults, and missing-id rejection | `…::test_create_cloud_agent_shapes_payload_and_returns_ids`, `…::test_create_cloud_agent_defaults`, `…::test_create_cloud_agent_rejects_response_without_id` |
| `get_run` / `list_artifacts` paths, agent-id fallback, artifact filtering | `…::test_get_run_and_artifacts_use_the_created_agent_id`, `…::test_get_run_falls_back_to_run_id_before_create`, `…::test_list_artifacts_returns_empty_for_non_list_items` |
| `EvalMetadata.expected_decision` rejects an out-of-vocabulary verdict | `tests/evidence/test_packet_evals.py::test_eval_metadata_rejects_out_of_vocabulary_expected_decision` |

## The behavioural assertion per module (not structural-only)

- **`recovery.py`** — every mode's call is observed through a recorded kill
  helper, a real sleeper process group is actually killed, and a kill helper
  that raises propagates instead of yielding `cleaned=True`. The former
  `assert cleaned is True` terminal assertion was removed from
  `tests/reliability/test_cd_degradation.py`, which now covers only the
  diagnostic bundle.
- **`similar.py`** — scores, ordering, thresholds, limits, and input
  non-mutation are asserted; `_git_change_candidates` is driven against a real
  `git init` fixture repo (newest-first, paths, 40-char SHAs) and against the
  no-repo paths.
- **`ingest.py`** — `ingest_requirements()` runs against fixture bodies and
  files; the assertions are on `IngestResult.source` / `source_ref` /
  `fenced_text`, and on each `Requirement`'s id, text, kind, state, and
  evidence paths. Every private helper named by the finding is exercised
  through that public entry point.
- **`node.py`** — detection, argv, and the run outcome are asserted against
  fixture trees with a fake `_run_cmd`; the fail-closed cases assert both the
  recorded argv (`runner.calls == []` on refusal) and the resulting
  `PrepResult` / `is_prep_install_failure` outcome.
- **`cursor_cloud/client.py`** — a fake `httpx.AsyncClient.request` records
  credentials, method, URL, and body; error paths assert the exception type
  *and* message; retry tests assert the exact attempt count.

## `verdict_vocab` (#769 survivor)

- The one uncovered branch is now exercised:
  `EvalMetadata.expected_decision="ship-it"` raises `ValidationError` naming
  the verdict vocabulary, mirroring the sibling case in
  `tests/evals/test_store.py::test_parse_rejects_unknown_expected_decision`.
- **No** `tests/evals/test_verdict_vocab.py` was added and no test pins the
  eleven string values (T-D6). `src/mergecraft/evals/verdict_vocab.py` still
  exists and is unchanged.

## Commands

```bash
uv run pytest tests/prep/test_node.py tests/reliability tests/pr/test_similar.py \
  tests/requirements/test_ingest.py tests/integrations tests/evidence/test_packet_evals.py -q
make lint
make typecheck
```
