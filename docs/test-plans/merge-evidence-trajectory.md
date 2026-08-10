# Merge evidence & gating — Batch C (trajectory) test plan (WC-T RED)

Wave plan: `.ignorelocal/waves/issues-merge-evidence-gating-wave-plan.md`
Worktree: `mergecraft-evi-c-trajectory` @ `wave/evi-c-trajectory`
Tests: `tests/evidence/test_trajectory.py`

Mirrors `docs/test-plans/merge-evidence-blast-radius.md` (Batch B) so the WC-T
close-out is directly comparable.

## Locked decisions exercised

| ID | Decision | Test(s) |
|----|----------|---------|
| **D8** | The record is self-contained — built from the MCP tool-call layer, never gated on #56 | `test_trajectory_record_is_populated_without_external_trace` |
| **D8** | A richer external trace is *optional enrichment*, declared in the schema | `test_external_trace_is_optional_enrichment` |
| **D7** | The packet is versioned; changing the `trajectory` section's shape bumps `PACKET_SCHEMA_VERSION` | `tests/evidence/test_packet_schema.py::test_packet_schema_version_is_pinned` |
| **D3** | The auditor emits the existing `Finding` model — no second finding type | every `_audit(...)` case asserts on `Finding.rule_id` / `.severity` |
| **D11** | Nothing here enables auto-merge; a blocking finding yields `failure`, not a merge | `test_high_severity_trajectory_finding_blocks_auto_merge` |
| Convention 5 | The auditor is pure — no filesystem, no network, no `os.environ`, no input mutation | `test_auditor_is_pure`, `test_audit_is_deterministic` |

## Contract matrix

| Issue | Layer | Scenario | Primary test |
|-------|-------|----------|--------------|
| **#49** | Unit | A clean trajectory fires nothing (control) | `test_clean_trajectory_fires_nothing` |
| **#49** | Unit | `changed-unread-file` fires and names the unread file | `test_changed_unread_file_fires` |
| **#49** | Unit | `changed-unread-file` stays silent with no read coverage | `test_changed_unread_file_is_suppressed_without_read_coverage` |
| **#49** | Unit | `ignored-tool-error` fires when a failed tool is never called again | `test_ignored_tool_error_fires` |
| **#49** | Unit | `ignored-tool-error` stays silent when the tool was retried | `test_ignored_tool_error_does_not_fire_when_the_tool_was_retried` |
| **#49** | Unit | `no-post-edit-verification` fires when verification predates the last edit | `test_no_post_edit_verification_fires` |
| **#49** | Unit | `repeated-tool-loop` fires at the threshold, not below it | `test_repeated_tool_loop_fires`, `…_does_not_fire_below_the_threshold` |
| **#49** | Unit | `unresolved-failure` fires on a *result* failure, distinct from a tool error | `test_unresolved_failure_fires` |
| **#49** | Unit | `suspicious-broad-edit` fires on an implausible file count | `test_suspicious_broad_edit_fires` |
| **#49** | Unit | `stale-assumption-after-failure` fires only when nothing was read in between | `test_stale_assumption_after_failure_fires`, `…_does_not_fire_when_something_was_read_in_between` |
| **#49** | Unit | `missing-completion-signal` fires on a run that stopped, not on an empty record | `test_missing_completion_signal_fires`, `…_does_not_fire_on_an_empty_record` |
| **#49** | Unit | Every check declares a severity and a recommended action | `test_every_named_check_has_a_severity_and_a_recommended_action` |
| **#43** | Integration | A high-severity trajectory finding reaches the packet verdict | `test_high_severity_trajectory_finding_blocks_auto_merge` |
| **#43** | Integration | The record is populated on the live `emit_run_packet` path | `test_trajectory_findings_reach_the_packet_from_a_real_run` |
| **#43** | Unit | The record forbids unknown fields and round-trips through JSON | `test_record_forbids_unknown_fields`, `test_record_round_trips_through_json` |
| **#49** | Unit | Trajectory findings never displace code findings from the inline budget | `test_trajectory_findings_never_crowd_out_code_findings` |

## Why the negative cases carry the weight

Three of the eight checks all describe "something went wrong", and a suite that
only asserts they fire could be satisfied by one over-eager check firing on
everything. Each is therefore pinned to a *distinct* trigger, with a negative
case that the other two do not cover:

| Check | Trigger | Distinguished from |
|---|---|---|
| `ignored-tool-error` | tool call raised; that tool is never called again | `stale-assumption…`, which requires a retry |
| `stale-assumption-after-failure` | tool call raised; retried with an identical signature and no intervening read | `ignored-tool-error`, which requires no retry |
| `unresolved-failure` | tool call *succeeded* but reported a failing outcome, never later resolved | both of the above, which key off transport errors |

The same reasoning drives `test_clean_trajectory_fires_nothing` and
`test_missing_completion_signal_does_not_fire_on_an_empty_record`: without
them, a check that returned a finding unconditionally would pass every
positive case in the file.

## xfail schedule

All cases carry a module-level `pytestmark = pytest.mark.xfail(reason="green
after W7/W8", strict=False)`. `strict=False` overrides the repo-wide
`xfail_strict=true`, so un-xfailing in W7/W8 flips each case to a pass without
breaking collection in between.

| Wave | Un-xfails |
|------|-----------|
| **W7** (#43) | the record cases — construction, `extra="forbid"`, JSON round-trip, MCP-only population, optional enrichment, live-run population |
| **W8** (#49) | the eight check cases, their negatives, purity, determinism, packet-decision blocking, noise budget |
