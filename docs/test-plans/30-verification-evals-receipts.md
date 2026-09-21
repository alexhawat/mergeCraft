# Verification, evals and receipts — test plans (R4–R6)

Scope: the RED/behavioural suites for the verification/evals/receipts wave
plan, on branch `wave/evals-second-target`. Owner of `tests/` and this file:
`test-creator`.

This document is shared by three waves. R4 (a second shadow target, #737) is
authored now; the R5 (golden-flywheel ingest) and R6 (CLI JSON schema
version) sections are reserved below and filled in when those RED suites land.

## R4 — a second shadow target (#737)

Wave outcome: a second shadow target — a different pinned model id and/or
prompt version — records through the **existing** `mergecraft.evidence.shadow`
recorder. A disagreement table is produced per target, grouped by lane and by
rule. The live path stays silent; the optional keyless comparison job fails
closed. The recorder is not rebuilt.

### Contract matrix

| Contract | Layer | Test node(s) |
| --- | --- | --- |
| A second target (distinct pinned model id and/or prompt version) records through the existing recorder; no second JSONL writer | Unit | `tests/evidence/test_shadow_second_target.py::test_second_target_records_through_the_existing_recorder` |
| The target is optional; a legacy call records a row with no target identity | Unit / edge | `…::test_recording_without_a_target_leaves_target_fields_unset` |
| `disagreement_report` distinguishes targets and groups by lane and by rule | Integration | `…::test_disagreement_report_distinguishes_targets_by_lane_and_rule` |
| A record without an outcome stays in the table with `disagreement=None` | Unit / edge | `…::test_report_keeps_a_record_without_an_outcome` |
| Silent live path: the recorder never calls `enforce_action` | Unit (structural) | `…::test_recording_never_calls_enforce_action` |
| Silent live path: a recorded disagreement never flips `decide_approval()` and never mutates the packet | Integration (structural) | `…::test_shadow_recording_does_not_flip_decide_approval` |
| Silent live path: a shadow-record failure never fails the live run/PR | Integration (structural) | `…::test_live_emit_swallows_a_shadow_recording_failure` |
| The comparison job records every (target, change) pair and publishes the table | Integration | `…::test_comparison_job_records_every_target_and_publishes_the_table` |
| The comparison job fails closed when recording fails — missing data is not agreement | Integration / error | `…::test_comparison_job_fails_closed_when_recording_fails` |
| A Logfire span is emitted on the recorder while the JSONL row is still written (JSONL remains the audit trail) | Integration | `…::test_recording_emits_a_shadow_span_and_keeps_the_jsonl_audit_trail` |
| The shadow-comparison CI job is optional and keyless — never a required PR check | CI structural | `tests/ci/test_shadow_comparison_job.py::test_shadow_comparison_job_is_non_blocking_and_keyless` |

### Pinned contracts (where the wave plan left a choice)

The wave plan names the deliverable ("a second target … a different pinned
model id and/or prompt version") but not the symbols. The suite pins these:

- **`ShadowTarget`** — a frozen model in `mergecraft.evidence.shadow` with
  `target_id` (the table label), `model` (the pinned model id), and
  `prompt_version` (optional). The second target is expressed as a second
  `ShadowTarget` value, not a settings block and not a second recorder.
- **`record_shadow_prediction(..., target=ShadowTarget | None = None)`** — the
  existing recorder grows one additive keyword. It stamps `target_id`,
  `target_model`, and `target_prompt_version` onto the row on both the
  gate-action and prediction paths. Omitting `target` preserves today's
  behaviour.
- **`disagreement_report` row keys** — rows add `target_id`, `target_model`,
  and `target_prompt_version` beside the existing lane/rule/action/outcome
  keys, so the table can be grouped by target as well as by lane and rule.
- **`mergecraft.evidence.shadow_compare.compare_shadow_targets(packets, *,
  targets, output_path, predictions=None, outcomes=None, tracer=None)`** — the
  keyless comparison job. It records one row per (target, change) through the
  existing recorder and returns the disagreement rows. It does **not** swallow
  a recording failure: that is the one path that fails closed.
- **`record_shadow_prediction(..., tracer=None)`** — when a tracer is supplied,
  one span of kind `mergecraft.shadow.prediction` is emitted with
  `mergecraft.shadow.change_id`, `mergecraft.shadow.target_id`, and
  `mergecraft.shadow.disagreement` attributes. The JSONL row is still written.

### Red / green inventory at authoring time

Six R4 contracts are RED under non-strict `xfail` markers (reason prefix
`green after R4:`). Four are green regression guards that must stay green:
`test_report_keeps_a_record_without_an_outcome`,
`test_recording_never_calls_enforce_action`,
`test_shadow_recording_does_not_flip_decide_approval`, and
`test_live_emit_swallows_a_shadow_recording_failure`. The CI structural test is
RED until the optional job lands. No marker uses `strict=True`.

### What this suite does not do

- It does not rebuild the recorder, and it does not add a second shadow log.
- It does not score shadow against "correct" outcomes: that needs adjudicated
  labels and is out of scope. Every rate here is provisional and uncalibrated.
- It does not make the comparison job a required check; the structural test
  asserts the opposite.

## R5 — golden-flywheel ingest (#738)

Reserved. The RED suite and contract matrix land with the R5 `test-creator`
dispatch. Ingest refuses without provenance, refuses `human` without
independent adjudication, and drops rather than mints a label. Ingested cases
join the structural replay path only and are never calibration labels.

## R6 — CLI JSON schema version (#777)

Reserved. The RED suite and contract matrix land with the R6 `test-creator`
dispatch. `CLI_JSON_SCHEMA_VERSION` is defined in `cli/`, independent of the
review snapshot version, at the same value, with no payload moved and `review/`
still not importing `cli/`.

## Commands

```bash
make lint
make typecheck
uv run pytest tests/evidence tests/jev --collect-only -q
uv run pytest tests/evidence/test_shadow_second_target.py tests/ci/test_shadow_comparison_job.py -q
```
