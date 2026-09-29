# Test plan — the handed-off halves: publisher identity, verdict capture, trajectory enforcement, read scoping, packaging

**Owner:** `test-creator` · **Branch:** `wave/handoff-sweep` · **Base:** `origin/main` @ `fc17fac4`
**Trace run:** service `mergecraft-dev` · wave.plan=handoff-sweep · run.id=`2e7cd4cf-8b33-49e3-a5d9-e82d09654b81`

Eight items that earlier plans addressed to work they could no longer touch. This
document maps each behaviour the RED suite pins to the tests that hold it. The
suite was written first, against the items' own contracts: every test that needs
a product seam which does not exist yet **fails** (no skip, no `xfail`), and the
green tests are real guards that the implementation waves must not regress.

**Status: RED as committed.** Collection is clean (174 tests), `make lint` and
`make typecheck` exit 0, and 54 tests fail because the behaviour they name is
not implemented yet. No test is skipped or xfailed to mask a contract. Each
implementation wave greens its section by building the behaviour, not by
touching the tests; the file that carries a now-satisfied assertion is reconciled
by `test-creator` after the fact.

Verification commands:

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest <paths> --collect-only -q   # collection diagnostic
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" MERGECRAFT_PYTEST_JOBS=0 uv run pytest <paths> -q
make lint && make typecheck
```

## Names this suite pins

A few seams were open when the items were handed off. The suite fixes them so
the implementation has one target.

| Surface | Name | Shape |
| --- | --- | --- |
| Sticky selector | `mergecraft.findings.ledger.select_sticky_progress_comment(ctx, comments, *, run_bound_comment_id=None)` | takes the `ToolContext` (the publisher set resolves from the run's credentials), not a bare comment list |
| Publisher set | `mergecraft.review.authorship.expected_publisher_logins(ctx)` | already shipped; the selector must consult it |
| Checkpoint reader | `mergecraft.mcp.checkout.recover_run_bound_review_state(ctx, *, pull_number)` | returns a state with `reviewed_head_sha: str` (`""` when unavailable), `round_index: int` (`0` when unavailable), `progress_comment_id: int | None` |
| Packet fields | `MergeEvidencePacket.reviewed_head_sha`, `MergeEvidencePacket.progress_comment_id` | both default `None`; written by the orchestrator, never an agent |
| Trajectory protocol | `mergecraft.evals.trajectory_scoring.load_trajectory_protocol(path)` → `TrajectoryProtocol(schema_version, sample_minimums, tolerance)` | a `sample_minimums` entry per trajectory check rule id |
| Trajectory scorer | `score_trajectory_labels(label_sets, *, protocol=None)`, `compare_trajectory_report(candidate, baseline, *, protocol)` | `quality_eligible` / `advisory` in the report's eligibility; comparison names failing rule ids |
| Trajectory CLI | `mergecraft eval trajectory-gate --protocol … --baseline … --candidate …` | exits 0 advisory with no protocol; non-zero outside tolerance |
| Verdict capture | `<evidence_dir>/judge-verdicts.jsonl`, one JSON line per saved verdict | the machine-written half of `JudgeCalibrationCase`; enabled by `MERGECRAFT_CAPTURE_VERDICTS=1` / `mergecraft review --capture-verdicts` |
| Native read denies | `mergecraft.agents.gates.build_claude_native_fs_denies(extra_secret_paths)` | emits `Read(<path>)` and `Edit(<path>)` per path |
| Read audit | `mergecraft.agents.claude.audit_read_boundary(records, *, checkout, tmpdir)` | returns the out-of-boundary paths and logs one run-record warning each |
| Batch manifest | `HumanBatchManifest` accepts a manifest-declared `batch_id` and case list | `golden-batch-001`'s nine ids stay a pinned fixture |

## Contract → test map

### Sticky selection trusts a publisher identity, never "any bot"

Selection resolves run-bound id → expected-publisher set → create-new-with-a-warning.
A `github-actions[bot]` comment is never selected by type alone.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| The run-bound id wins over the publisher scan | unit | `tests/findings/test_sticky_selection_author.py::test_the_run_bound_comment_id_wins_when_present` | red → authorship wave |
| The run-bound id alone selects on a job-token run (no publisher identity) | unit | `tests/findings/test_sticky_selection_author.py::test_the_run_bound_comment_id_alone_selects_on_a_job_token_run` | red → authorship wave |
| A run-bound id must still name a Bot carrying a ledger marker | unit | `tests/findings/test_sticky_selection_author.py::test_the_run_bound_comment_id_must_still_name_a_bot_and_carry_a_marker` | red → authorship wave |
| With an App publisher, its own bot is selected and a foreign App's is not | unit | `tests/findings/test_sticky_selection_author.py::test_an_app_publisher_selects_its_own_bot_and_not_a_foreign_app`, `::test_an_app_publisher_does_not_select_a_foreign_app_on_its_own` | red → authorship wave |
| Ledger-marker preference holds among expected-publisher comments | unit | `tests/findings/test_sticky_selection_author.py::test_ledger_marker_preference_holds_among_marked_publisher_comments` | red → authorship wave |
| A human marker is never selected | unit | `tests/findings/test_sticky_selection_author.py::test_a_human_comment_with_a_ledger_marker_is_not_selected` | red → authorship wave |
| A forged `github-actions[bot]` comment (with ledger markers, `withdrawn` included) is never selected | unit | `tests/findings/test_sticky_selection_author.py::test_a_github_actions_bot_comment_with_ledger_markers_is_not_selected_on_a_job_token_run` | red → authorship wave |
| With an empty publisher set the writer creates a new comment and warns why | integration | `tests/findings/test_sticky_selection_author.py::test_persist_with_an_empty_publisher_set_creates_and_warns` | red → authorship wave |
| `hydrate`, `persist` and `upsert` keep ignoring a human marker | integration | `tests/findings/test_sticky_selection_author.py::test_hydrate_ignores_a_human_ledger_marker`, `::test_persist_ignores_a_human_ledger_marker`, `::test_upsert_ignores_a_human_ledger_marker` | green (guard) |

### The read-only operator view has no run context

`mergecraft findings ledger` never feeds a run. With no App configured it reads a
Bot-type comment and says the result is unauthenticated; with an App slug it
prefers that App's bot over a job bot.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| No App configured: the Bot-type read is labelled unauthenticated | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_notes_an_unauthenticated_bot_read` | red → authorship wave |
| A configured App slug beats a job bot's markers | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_prefers_the_configured_app_slug_over_the_job_bot` | green (guard) |
| Existing read-only / bot-sticky / human-marker behaviour is unchanged | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_is_read_only`, `::test_ledger_command_reads_a_bot_sticky`, `::test_ledger_command_ignores_a_human_comment_with_ledger_markers`, `::test_ledger_command_prefers_the_bot_sticky_over_a_human_marker` | green (guard) |

### The incremental checkpoint comes from the trusted workflow run

The checkpoint and round index are read from the newest successful
`pull_request_target` run of the review workflow for this PR, through its evidence
artefact. Anything untrusted or unreadable is ignored, and unavailability is
fail-closed with a named warning.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| The newest trusted run's `reviewed_head_sha`, trusted-run count and comment id are returned | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_reviewed_head_sha_is_the_newest_trusted_runs_value` | red → run-bound identity wave |
| The reader lists the workflow at the `pull_request_target` event | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_reader_lists_the_trusted_workflow_with_the_pull_request_target_event` | red → run-bound identity wave |
| A `pull_request`-event run, a failed run, another PR's run and a run with no PR are ignored | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_pull_request_event_failed_and_other_pr_runs_are_ignored` | red → run-bound identity wave |
| An expired artefact falls back and warns | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_an_expired_artifact_falls_back_and_warns` | red → run-bound identity wave |
| A missing artefact falls back without selecting a comment | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_a_missing_artifact_falls_back_without_selecting_a_comment` | red → run-bound identity wave |
| An Actions API error falls back and warns | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_an_api_error_falls_back_and_warns` | red → run-bound identity wave |
| No trusted run is fail-closed | unit | `tests/mcp/test_checkout_run_bound_checkpoint.py::test_no_trusted_run_is_fail_closed` | red → run-bound identity wave |

### The evidence packet carries the run-bound review identity

Both fields are written by the orchestrator, so a packet names exactly what it
reviewed and which sticky it owns. Neither is agent-controlled.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| `reviewed_head_sha` is the checkout head | integration | `tests/evidence/test_run_packet.py::test_packet_records_the_orchestrator_reviewed_head_sha` | red → run-bound identity wave |
| `progress_comment_id` is the run's sticky id | integration | `tests/evidence/test_run_packet.py::test_packet_records_the_run_bound_progress_comment_id` | red → run-bound identity wave |
| A run with no checkout or sticky records null, never a fabricated value | integration | `tests/evidence/test_run_packet.py::test_packet_run_bound_fields_default_to_none_without_run_state` | red → run-bound identity wave |
| The schema and the JSON output declare both fields; each defaults to `None` | unit | `tests/evidence/test_packet_schema.py::test_packet_schema_declares_run_bound_review_fields`, `::test_packet_run_bound_fields_default_to_none` | red → run-bound identity wave |
| Both fields survive a JSON round trip | unit | `tests/evidence/test_packet_round_trip.py::test_run_bound_review_fields_round_trip_through_json` | red → run-bound identity wave |

### The review job proves its identity through the run, not a shared bot

The job needs the Actions read scope to download the trusted run's artefact, and
no review rung may declare the forgeable shared job bot as its login.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| The `review` job grants `actions: read` | integration | `tests/ci/test_mergecraft_workflow_permissions.py::TestReviewJobRunBoundIdentity::test_review_job_grants_actions_read` | green (guard) |
| Every `MERGECRAFT_REVIEWER_BOT_LOGIN` fallback resolves to an empty string; none names `github-actions[bot]` | integration | `tests/ci/test_mergecraft_workflow_permissions.py::TestReviewJobRunBoundIdentity::test_no_rung_declares_the_shared_job_bot_as_its_login` | red → run-bound identity wave |

### Every saved verifier verdict can be captured for judge calibration

Capture is off by default; when on it writes one redacted JSON line per verdict —
`confirm`, `downgrade` and `drop` alike — in the machine-written half of the
strict calibration case.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| Capture off writes nothing | unit | `tests/mcp/test_verdict_capture.py::test_capture_off_writes_nothing` | green (guard) |
| Capture off keeps the existing loguru verdict line | unit | `tests/mcp/test_verdict_capture.py::test_capture_off_keeps_the_loguru_verdict_line` | green (guard) |
| Capture on appends exactly one line per verdict, drop included | integration | `tests/mcp/test_verdict_capture.py::test_capture_on_appends_one_line_per_verdict` | red → authorship/verdict wave |
| Each line validates as the strict calibration case minus its adjudication fields | unit | `tests/mcp/test_verdict_capture.py::test_captured_line_validates_as_the_calibration_case_minus_adjudication` | red → authorship/verdict wave |
| The saved verdict carries a pinned judge and the policy fields | unit | `tests/mcp/test_verdict_capture.py::test_captured_record_carries_the_pinned_judge_and_policy_fields` | red → authorship/verdict wave |
| A canary in the finding body is redacted before the line is written | unit | `tests/mcp/test_verdict_capture.py::test_a_canary_in_the_finding_body_is_redacted` | red → authorship/verdict wave |
| The offline review path exposes the one enabling flag | functional | `tests/mcp/test_verdict_capture.py::test_offline_review_exposes_the_capture_flag` | red → authorship/verdict wave |

### The trajectory scorer reads an approved protocol and compares a baseline

With no approved protocol the gate is advisory and honest; with one, quality
eligibility needs independence and every pre-registered minimum, and a comparison
against a frozen baseline fails outside tolerance naming the check.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| The protocol loader reads schema version, minimums and tolerance | unit | `tests/evals/test_trajectory_protocol.py::test_loader_reads_the_protocol_file` | red → trajectory wave |
| The loader rejects an unknown schema version | unit | `tests/evals/test_trajectory_protocol.py::test_loader_rejects_an_unknown_schema_version` | red → trajectory wave |
| With no protocol the report is advisory and not quality-eligible | unit | `tests/evals/test_trajectory_protocol.py::test_without_a_protocol_the_report_is_advisory` | red → trajectory wave |
| Every minimum met and independent labels → quality-eligible | unit | `tests/evals/test_trajectory_protocol.py::test_a_protocol_with_every_minimum_met_is_quality_eligible` | red → trajectory wave |
| One check below its minimum → not eligible, and it is named | unit | `tests/evals/test_trajectory_protocol.py::test_a_check_below_its_minimum_is_named` | red → trajectory wave |
| Non-independent labels are not quality-eligible even with a protocol | unit | `tests/evals/test_trajectory_protocol.py::test_non_independent_labels_are_not_quality_eligible_even_with_a_protocol` | red → trajectory wave |
| A candidate within tolerance passes; outside it fails naming the check | unit | `tests/evals/test_trajectory_protocol.py::test_comparison_passes_within_tolerance`, `::test_comparison_fails_naming_the_check` | red → trajectory wave |
| The gate exits 0 and says advisory with no protocol | functional | `tests/evals/test_trajectory_protocol.py::test_gate_is_advisory_and_exits_zero_without_a_protocol` | red → trajectory wave |
| The gate passes within tolerance and fails outside it naming the check | functional | `tests/evals/test_trajectory_protocol.py::test_gate_passes_within_tolerance`, `::test_gate_fails_outside_tolerance_naming_the_check` | red → trajectory wave |
| One Make target, discoverable, calling the CLI gate | integration | `tests/ci/test_makefile_targets.py::test_eval_trajectory_gate_target_has_a_help_string` | red → trajectory wave |
| The gate is one step in the existing eval job; no new job appears | integration | `tests/ci/test_eval_pr_gate.py::test_eval_gate_job_runs_the_trajectory_gate`, `::test_trajectory_gate_adds_no_new_required_job` | red → trajectory wave |

### The Claude reviewer cannot read the run's credential material

The OS identity is the boundary; deny rules cover what identity cannot move;
reads that actually happened are recorded.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| The driver passes every image secret path to the native deny builder | unit | `tests/agents/test_claude_read_scope.py::test_driver_passes_the_image_secret_paths_to_the_native_fs_deny_builder` | red → read-scoping wave |
| The resulting `Read(...)` deny rules reach the Claude invocation | unit | `tests/agents/test_claude_read_scope.py::test_native_read_denies_reach_the_claude_invocation` | red → read-scoping wave |
| The builder emits a `Read` and an `Edit` rule per path | unit | `tests/agents/test_claude_read_scope.py::test_the_builder_emits_read_and_edit_rules_for_each_secret_path` | green (guard) |
| An out-of-boundary read warns and names the path | unit | `tests/agents/test_claude_read_log_check.py::test_a_read_outside_the_boundary_warns_and_names_the_path` | red → read-scoping wave |
| In-boundary reads record nothing | unit | `tests/agents/test_claude_read_log_check.py::test_reads_inside_the_checkout_or_run_tmpdir_record_nothing` | red → read-scoping wave |
| Non-read tools are not audited | unit | `tests/agents/test_claude_read_log_check.py::test_non_read_tools_are_not_audited` | red → read-scoping wave |
| A relative path escaping the checkout is reported | unit | `tests/agents/test_claude_read_log_check.py::test_a_relative_path_escaping_the_checkout_is_reported` | red → read-scoping wave |
| The Codex auth file is written root-only (`0600`) | unit | `tests/security/test_agent_readable_secrets.py::test_codex_auth_file_is_written_root_only` | red → read-scoping wave |
| In the action image, no candidate credential path is readable by the agent user | integration (root-gated) | `tests/security/test_agent_readable_secrets.py::TestCredentialPathsAreUnreadableToTheAgentUser::test_no_credential_path_is_readable_by_the_agent_user` | skipped off-image; red in-image until the read-scoping wave |

### The drivers use the documented `push_branch` MCP tool name

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| Gemini's `excludeTools` carries `mcp_mergecraft_push_branch`, not the bare name | unit | `tests/agents/test_harness_deny_list_pin.py::test_gemini_exclude_tools_uses_documented_push_branch_name` | red → driver-spelling wave |
| Codex's subagent instructions name `mergecraft_push_branch` | unit | `tests/agents/test_harness_deny_list_pin.py::test_codex_subagent_instructions_use_documented_push_branch_name` | red → driver-spelling wave |
| Claude and OpenCode already use the documented name | unit | `tests/agents/test_harness_deny_list_pin.py::test_claude_disallowed_tools_use_documented_push_branch_name`, `::test_opencode_permission_deny_uses_documented_push_branch_name`, `::test_format_mcp_tool_ref_matches_documented_cli_name`, `::test_harness_mcp_cli_name_fixture_exists` | green (guard) |

### The wheel excludes only modules with no runtime caller

The packaging config drops the six test/script-facing modules and the one with no
caller at all, while `evals/corpora.py` (a shipped CLI import) stays. The real
installed-wheel proof is `make test-wheel-corpus`, run in CI's `build-dist` job.

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| The wheel `exclude` list is exactly the modules with no runtime caller | unit | `tests/ci/test_wheel_contents.py::test_wheel_excludes_exactly_the_modules_with_no_runtime_caller` | red → packaging wave |
| `evals/corpora.py` is not excluded | unit | `tests/ci/test_wheel_contents.py::test_wheel_keeps_the_module_with_a_runtime_caller` | red → packaging wave |
| Every excluded path exists on disk; the kept module exists | unit | `tests/ci/test_wheel_contents.py::test_every_excluded_path_exists_on_disk`, `::test_the_kept_runtime_module_exists` | green (guard) |

### A second human batch is declared by its manifest

| Behaviour | Layer | Test | Status |
| --- | --- | --- | --- |
| A manifest declaring its own batch id and case list validates | unit | `tests/evals/test_human_batch.py::test_a_manifest_declaring_batch_002_with_its_own_ids_validates` | red → batch-generalisation wave |
| The first batch's frozen nine still validate unchanged | unit | `tests/evals/test_human_batch.py::test_batch_001_frozen_set_still_validates_unchanged` | green (guard) |
| The first batch still requires exactly its frozen nine | unit | `tests/evals/test_human_batch.py::test_batch_001_still_requires_exactly_the_frozen_nine` | green (guard) |
| A later batch's rows keep the recovered-evidence agreement guard | unit | `tests/evals/test_human_batch.py::test_batch_002_rows_keep_the_agreement_guard` | green (guard) |

## Skip preconditions

One test self-skips outside the action image, matching the other root-gated
in-image suites. Its skip reason is named on the test:

* `tests/security/test_agent_readable_secrets.py::TestCredentialPathsAreUnreadableToTheAgentUser::test_no_credential_path_is_readable_by_the_agent_user`
  skips unless **euid 0**, **Linux**, `setpriv` on `PATH`, and an image
  `mergecraft` user — i.e. the privileged review container. The rest of the
  module (the `0600` Codex auth write) runs on every host.

No other test in this suite skips or xfails; every unmet contract is a plain
failure so a missing product seam can never read as a pass.

## Scenario classes

* **Happy path** — the trusted run's head and comment id flow into the packet and
  the checkpoint; an App publisher selects its own sticky; every verdict lands in
  one calibration line; a protocol with every minimum met is quality-eligible; a
  comment within tolerance passes its baseline comparison; an in-boundary read
  records nothing.
* **Edge cases** — a run-bound id on a job-token-only run; an id naming a human or
  a markerless bot; a foreign App's bot beside the expected one; the same head
  with a comment queue out of order; ledger-marker preference among publishers;
  null run state producing null packet fields; a candidate exactly at tolerance;
  a path that escapes the checkout with `..`; a protocol minimum set the labels
  do not reach.
* **Error handling** — a forged `github-actions[bot]` comment carrying
  `withdrawn` markers; an empty publisher set (create + warn, never select);
  an expired artefact, a missing artefact and an Actions API error (fail closed,
  warn); an unknown protocol schema version; capture off writing nothing and
  never losing the loguru line; a canary in a finding body redacted before it is
  written; the in-image readability sweep.

## Reconciliation log

The implementation waves turn each red section green; `test-creator` then
re-reads this document and reconciles the status column. No test is edited by an
implementation wave, and no assertion is weakened to reach green. This section
records each pass.
