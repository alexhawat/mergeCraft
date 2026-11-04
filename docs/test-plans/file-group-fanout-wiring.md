# Test plan — file-group fan-out wired into roster dispatch

**Owner:** `test-creator` · **Branch:** `feat/file-group-fanout-wiring` · **Base:** `origin/main` @ `f312aa81` · **Issue:** #1031

`src/mergecraft/review/file_group_fanout.py` already plans at most six balanced read-only
file groups from a large diff and degrades a failed group to a recorded row, but nothing
calls it. This suite pins the wiring: a `review.fileGroupFanout` setting (off by default),
a server-side dispatch of one reviewer per group under the `file-group/<group-id>` agent
id, findings aggregated through `record_reviewer_dispatch_run`, a failed group recorded as
one run-scoped `Minor` finding on the run-health partition, and a small diff that keeps
today's single-agent path exactly.

The suite is written first and is **red until the implementation lands**: every new test
below fails for the behaviour it names, none is skipped, and none carries an `xfail`. A
handful of guard tests are green on the base commit on purpose (marked *guard* below):
they pin behaviour the implementation must not break.

Rules the suite enforces throughout:

* **Off means off.** With the setting absent or `enabled: false`, nothing is planned and
  nothing is dispatched, and `main` never calls the fan-out.
* **Small diffs are untouched.** Enabled, but below both size thresholds, the secondary
  roster's dispatches are identical to a run without the fan-out.
* **A group failure degrades, never fails.** One failed group is one recorded dispatch
  error plus one run-health `Minor` row; the other groups' findings stand; the roster's
  hard error stays `None` and `apply_roster_failure` leaves the result alone.
* **Sequential unless asked.** `concurrency` defaults to 1 because the dispatch core
  temporarily rewrites `tool_context.agent_id`.

Verification commands:

```bash
make lint
make typecheck
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/review tests/config -q   # scoped iteration
uv run pytest --collect-only -q tests/review tests/config             # collection diagnostic
```

## Names this suite pins

| Surface | Name | Shape |
| --- | --- | --- |
| Settings model | `mergecraft.config.settings.FileGroupFanoutSettings` | `enabled: bool = False`; `max_groups: int = 6` (`maxGroups`, 1..12); `min_diff_lines: int = 800` (`minDiffLines`); `min_files: int = 20` (`minFiles`); `binding: str \| None = None`; `concurrency: int = 1` (1..6); `per_group_timeout_s: int = 600` (`perGroupTimeoutS`); unknown keys rejected |
| Settings field | `ReviewSettings.file_group_fanout` | alias `fileGroupFanout`; a by-alias dump validates back to an equal model |
| Dispatch entry | `mergecraft.review.roster_execution.run_file_group_reviewers(*, tool_context, base_run_ctx, settings, payload, repo_root, remaining_timeout_s=None) -> FanoutSummary` | `remaining_timeout_s` has the same shape as `run_pending_roster_reviewers`' (`Callable[[], float \| None] \| None`) |
| Diff source | `RepoToolState.diff_path` of the primary repo | no path or an unreadable file means an empty summary, no exception |
| Group agent id | `file-group/<group-id>` | `group-1`, `group-2`, … in plan order |
| Group prompt | rendered instructions of each group dispatch | the group's own paths, the shared diff path, the roster submit instructions (`_ROSTER_SUBMIT_INSTRUCTIONS`), and no other group's paths |
| Aggregation | `ToolState.reviewer_dispatch_runs` | one `ReviewerRun` per successful group, `agent_id` = the group id, `model_slug` = the dispatched model, findings = only that group's new rows |
| Binding | `binding: None` | reuses the primary reviewer's registry binding; a named binding is resolved with `Registry.resolve_agent_ref` |
| Failure record | `record_reviewer_dispatch_error(tool_state, agent_id="file-group/<id>", reason=…)` | for a raised exception, a failed `AgentResult`, a missing binding, a missing credential and a timeout |
| Run-health row | a `Finding`-shaped row appended to `ToolState.agent_findings` | `scope="run"`, `severity="Minor"`, `tool="review"`, message names the group and the reason; validates through `typed_findings_from_rows_with_drops` with no drops and lands in `run_health` through `evidence.build._partition_findings` |
| Planner concurrency | `file_group_fanout.dispatch_file_groups(plan, dispatch, *, on_failure=None, concurrency=1)` | at most `concurrency` groups in flight; results and failures stay in plan order |
| Per-group timeout | the timeout each group dispatch runs under | `min(perGroupTimeoutS, binding timeoutS, remaining run budget)` |
| Main wiring | `mergecraft.main._run_server_roster_reviewers_if_needed` | calls `run_file_group_reviewers` before `run_pending_roster_reviewers`, only when enabled, and returns the roster summary unchanged |
| Provenance | `prepare_terminal_submission` / `stamped_findings_for_terminal_submission` | a group run's findings keep `raised_by = "file-group/<id>"` and `raised_by_model`, with one or two registry reviewers |

The run-health row deliberately goes into `ToolState.agent_findings` rather than a new
tool-state field: that is the lane the evidence-packet loader already reads, and
run-scoped rows there partition into `run_health` without any change to the packet
builder. Recording it after the groups have finished (the `on_failure` hook of
`dispatch_file_groups`) keeps it out of every group's own findings.

## Contract → test map

### Settings (`tests/config/test_file_group_fanout_settings.py`)

| Contract | Layer | Tests |
| --- | --- | --- |
| Off and sequential by default, on `ReviewSettings` and on the standalone model | unit | `test_review_settings_default_fanout_is_off_and_sequential`, `test_standalone_model_defaults_match_the_review_default` |
| camelCase aliases populate every field; field names populate too | unit | `test_camel_case_aliases_populate_every_field`, `test_field_names_populate_too` |
| A by-alias dump round-trips | unit | `test_dump_by_alias_round_trips` |
| `maxGroups` 1..12 and `concurrency` 1..6, inclusive; the error names the field and the bound | unit, edge + error | `test_out_of_range_bounds_are_rejected_naming_the_field` (4 cases), `test_inclusive_bounds_are_accepted` (4 cases) |
| Unknown keys inside the block are rejected at that key | error | `test_unknown_fanout_key_is_rejected` |
| The YAML block loads through `load_repo_settings`, unspecified keys keep defaults | integration | `test_repo_config_yaml_block_loads` |
| This repository's own config keeps fan-out off | integration | `test_this_repository_keeps_fanout_off` |

### Planner and dispatcher (`tests/review/test_file_group_fanout.py`)

| Contract | Layer | Tests |
| --- | --- | --- |
| Either threshold triggers fan-out: 25 files × 10 lines and 5 files × 200 lines fan out, 5 files × 10 lines does not; boundaries at exactly 20 files, exactly 800 lines, and 19 files / 798 lines | unit, edge (*guard*) | `test_either_threshold_triggers_fanout` (6 cases) |
| Thresholds come from the caller | unit (*guard*) | `test_thresholds_are_caller_supplied` |
| `concurrency` defaults to 1: start/finish strictly alternate | unit | `test_dispatch_is_sequential_by_default`, `test_concurrency_one_is_strictly_sequential` |
| At most `concurrency` groups in flight, capped by the group count | unit, edge | `test_concurrency_bounds_groups_in_flight` (2, 3, 6, 12) |
| A failure under concurrency is still recorded, never raised, in plan order | unit, error | `test_concurrent_dispatch_still_degrades_a_failed_group_in_plan_order` |

### Roster wiring (`tests/review/test_file_group_fanout_wiring.py`)

The tests drive `run_file_group_reviewers` against a real registry loaded from a
temporary `.mergecraft/config.yaml`, with the provider runtime, credential check, model
resolution and instruction rendering replaced by recording fakes (the same seams
`tests/review/test_roster_execution.py` patches).

| Contract | Layer | Tests |
| --- | --- | --- |
| Disabled (absent or `enabled: false`) returns an empty summary and dispatches nothing, even for a large diff | integration | `test_disabled_fanout_returns_an_empty_summary_and_dispatches_nothing` (2 cases) |
| Enabled + small diff: the secondary roster's calls, runs and summary equal a run without the fan-out | integration | `test_small_diff_keeps_the_secondary_call_sequence_identical` |
| No diff path, or a diff path missing on disk: empty summary, no exception | edge | `test_enabled_without_a_readable_diff_dispatches_nothing` (2 cases) |
| Large diff: one dispatch per planned group, ids `file-group/group-1..N` | integration | `test_large_diff_dispatches_one_reviewer_per_planned_group` |
| Never more than `maxGroups` dispatches | edge | `test_group_count_never_exceeds_max_groups` (1, 3, 6) |
| Each group's prompt: its own paths, the shared diff path, the roster submit instructions, no other group's paths | integration | `test_each_group_prompt_names_only_its_own_paths_and_the_shared_diff` |
| Findings land on `reviewer_dispatch_runs` under the group id with `model_slug`; `tool_context.agent_id` is restored | integration | `test_group_findings_are_recorded_under_the_group_agent_id_with_model_slug` |
| `binding` selects the group model; `None` reuses the primary reviewer | integration | `test_configured_binding_selects_the_group_model` (with the primary case covered above) |
| A raising group and a failed-result group each become one dispatch error plus one run-scoped `Minor` row on `run_health` | integration, error | `test_a_failed_group_degrades_to_one_run_health_minor` (2 cases) |
| The other groups' findings are kept; the run-health row is never inside a group run | integration, error | `test_a_failed_group_keeps_every_other_groups_findings` |
| A group failure is never a roster hard error; the secondary still dispatches; `apply_roster_failure` is a no-op | integration, error | `test_a_failed_group_is_never_a_roster_hard_error` |
| `concurrency: 1` and the default are strictly sequential | integration | `test_sequential_fanout_finishes_each_group_before_starting_the_next` (2 cases) |
| `concurrency: 3` peaks at exactly three in flight | integration | `test_concurrency_three_never_runs_more_than_three_groups_at_once` |
| `roster_dispatch_gaps` ignores group rows, both after a real fan-out and in isolation | integration; unit (*guard*) | `test_roster_gaps_ignore_file_group_rows_after_a_fanout`, `test_roster_gaps_name_only_registry_reviewers_beside_group_rows` |
| A missing binding is a recorded error naming the binding, no exception, no provider call | error | `test_missing_binding_is_a_recorded_error_not_an_exception` |
| A missing credential is a recorded error per group, no provider call | error | `test_missing_credential_is_a_recorded_error_per_group` |
| The group timeout is the smallest of `perGroupTimeoutS`, the binding's `timeoutS` and the remaining run budget | integration, error | `test_group_timeout_is_the_smallest_of_its_three_bounds` (3 cases; each hangs a fake reviewer and asserts the group is cut off in well under the hang) |
| `main` calls the fan-out after the primary and before the secondary roster, passing the run's tool context, run context, payload and a remaining-budget callable | functional | `test_main_runs_the_fanout_before_the_secondary_roster_when_enabled` |
| `main` skips the fan-out when disabled | functional | `test_main_skips_the_fanout_when_disabled` |
| `main` never folds a degraded fan-out into the roster result | functional, error | `test_main_never_folds_a_degraded_fanout_into_the_roster_result` |

### Provenance (`tests/review/test_publication_raised_by.py`)

| Contract | Layer | Tests |
| --- | --- | --- |
| A group run's finding keeps `raised_by = "file-group/<id>"` and its model, beside the primary, with one or two registry reviewers, and renders as a provenance line | unit | `test_file_group_findings_keep_their_group_id_at_terminal_submission` (2 cases) |
| Any other stray reviewer id still reads as `unknown` | unit (*guard*) | `test_a_foreign_reviewer_id_still_reads_as_unknown_beside_file_groups` |
| End to end through `submit_review_verdict`: a server-recorded group run reaches the terminal submission under its id | integration | `test_submit_review_verdict_stamps_raised_by_from_a_file_group_run` |

## Live validation (operator step, not automated)

The suite cannot prove that real providers follow the group prompt. After the
implementation merges, an operator enables `review.fileGroupFanout.enabled: true` on a
branch, opens a pull request with at least 20 changed files or 800 added lines, and
confirms the evidence packet shows `file-group/*` reviewer runs and that a forced group
failure appears under `run_health`. #1031 stays open until then.

## Amendments

None yet. A test changed after an implementation escalation gets a one-line rationale
here.
