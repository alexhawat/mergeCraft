# Verification, evals and receipts — test plans (R4–R6)

Scope: the RED/behavioural suites for the verification/evals/receipts wave
plan, on branch `wave/evals-second-target`. Owner of `tests/` and this file:
`test-creator`.

This document is shared by three waves. R4 (a second shadow target, #737) and
R5 (golden-flywheel ingest, #738) are authored; the R6 (CLI JSON schema
version) section is reserved below and filled in when that RED suite lands.

## R4 — a second shadow target (#737)

Wave outcome: a second shadow target — a different pinned model id and/or
prompt version — records through the **existing** `mergecraft.evidence.shadow`
recorder. A disagreement table is produced per target, grouped by lane and by
rule. The live path stays silent; the optional keyless comparison job fails
closed. The recorder is not rebuilt.

### Contract matrix

| Contract | Layer | Test node(s) | Status |
| --- | --- | --- | --- |
| A second target (distinct pinned model id and/or prompt version) records through the existing recorder; no second JSONL writer | Unit | `tests/evidence/test_shadow_second_target.py::test_second_target_records_through_the_existing_recorder` | ✅ pass |
| The target is optional; a legacy call records a row with no target identity | Unit / edge | `…::test_recording_without_a_target_leaves_target_fields_unset` | ✅ pass |
| `disagreement_report` distinguishes targets and groups by lane and by rule | Integration | `…::test_disagreement_report_distinguishes_targets_by_lane_and_rule` | ✅ pass |
| A record without an outcome stays in the table with `disagreement=None` | Unit / edge | `…::test_report_keeps_a_record_without_an_outcome` | ✅ pass |
| Silent live path: the recorder never calls `enforce_action` | Unit (structural) | `…::test_recording_never_calls_enforce_action` | ✅ pass |
| Silent live path: a recorded disagreement never flips `decide_approval()` and never mutates the packet | Integration (structural) | `…::test_shadow_recording_does_not_flip_decide_approval` | ✅ pass |
| Silent live path: a shadow-record failure never fails the live run/PR | Integration (structural) | `…::test_live_emit_swallows_a_shadow_recording_failure` | ✅ pass |
| The comparison job records every (target, change) pair and publishes the table | Integration | `…::test_comparison_job_records_every_target_and_publishes_the_table` | ✅ pass |
| The comparison job fails closed when recording fails — missing data is not agreement | Integration / error | `…::test_comparison_job_fails_closed_when_recording_fails` | ✅ pass |
| A Logfire span is emitted on the recorder while the JSONL row is still written (JSONL remains the audit trail) | Integration | `…::test_recording_emits_a_shadow_span_and_keeps_the_jsonl_audit_trail` | ✅ pass |
| The shadow-comparison CI job is optional and keyless — never a required PR check | CI structural | `tests/ci/test_shadow_comparison_job.py::test_shadow_comparison_job_is_non_blocking_and_keyless` | ✅ pass |

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

### Red / green inventory at reconciliation time

R4.2 (implementation `bbb1e3aa`) satisfied every contract, so the reconciliation
run (`f8c575d3-5a2f-433a-9e6a-8c978fcd25d9`) removed all seven non-strict
`xfail` markers — six in `tests/evidence/test_shadow_second_target.py` and one
in `tests/ci/test_shadow_comparison_job.py`. All eleven R4 tests are now real
passes (11 passed, 0 xfail, 0 xpass), and the four regression guards stayed
green throughout. **Rationale:** the markers were `strict=False` by design, so
the implementation wave made them `XPASS`; the session-level XPASS ratchet
(`tests/conftest.py` + `scripts/check_xpass.py`) cannot go green until the
satisfied markers are removed, and only `test-creator` may edit `tests/`.

### What this suite does not do

- It does not rebuild the recorder, and it does not add a second shadow log.
- It does not score shadow against "correct" outcomes: that needs adjudicated
  labels and is out of scope. Every rate here is provisional and uncalibrated.
- It does not make the comparison job a required check; the structural test
  asserts the opposite.

## R5 — golden-flywheel ingest (#738)

Wave outcome: production false positives and human dismissals are ingested into
the **existing** structural bank (`evals/cases`) as versioned cases, each
carrying an explicit provenance string. The ingest refuses a candidate without
provenance and **drops** it rather than minting a label; it refuses to write
`human` unless the candidate carries an independent adjudication record from the
existing `adjudicate_label` writer. It reuses `tier_for_provenance` — one
vocabulary, not two. Ingested cases join `eval replay-bank` as structural cases
only and are never calibration labels. No new eval harness is built and no new
required PR check is added.

### Contract matrix

| Contract | Layer | Test node(s) | Status |
| --- | --- | --- | --- |
| Ingest writes an `agent-seeded` structural case with its persisted provenance; `tier_for_provenance` reads it back as `none` | Unit / integration | `tests/evals/test_flywheel_ingest.py::test_ingest_writes_an_agent_seeded_case_with_its_provenance` | RED (xfail) |
| `human` is written only when the candidate carries an independent adjudication record | Integration | `…::test_ingest_writes_a_human_adjudicated_case_when_the_record_is_independent` | RED (xfail) |
| A model adjudicator's label is written at tier `model`, never upgraded | Unit | `…::test_ingest_writes_an_llm_adjudicated_case_at_the_model_tier` | RED (xfail) |
| One vocabulary: the persisted string is exactly `provenance_for(record)` | Unit | `…::test_ingest_writes_the_provenance_the_adjudication_module_derives` | RED (xfail) |
| Refuse a candidate without provenance; drop it, no file, tier `none` | Unit / error | `…::test_ingest_refuses_a_candidate_without_provenance_and_drops_it` | RED (xfail) |
| An unknown provenance string is refused, never privileged | Unit / edge | `…::test_ingest_refuses_an_unknown_provenance_string` | RED (xfail) |
| Refuse to mint `human` without an adjudication record (the claim is not independent) | Integration / error | `…::test_ingest_refuses_to_mint_human_without_an_adjudication_record` | RED (xfail) |
| Refuse a `human` claim backed by a non-independent (model-tier) record | Integration / error | `…::test_ingest_refuses_a_human_claim_backed_by_a_non_independent_record` | RED (xfail) |
| An `agent-seeded` candidate is never silently upgraded to `human` | Unit | `…::test_ingest_never_marks_an_agent_seeded_case_human` | RED (xfail) |
| A rejected candidate leaves no case file and reports no path | Unit / error | `…::test_a_rejected_candidate_leaves_no_case_and_no_label` | RED (xfail) |
| Fail-closed is per candidate: a bad row does not abort the batch | Integration / error | `…::test_a_rejected_candidate_does_not_abort_the_batch` | RED (xfail) |
| An empty candidate list writes nothing and reports zero counters | Unit / edge | `…::test_ingest_of_an_empty_candidate_list_writes_nothing` | RED (xfail) |
| Ingested cases join `run_structural_replay` and carry no detection/calibration block | Integration / functional | `…::test_ingested_cases_join_the_structural_replay_bank` | RED (xfail) |
| Ingested `agent-seeded` rows never make a calibration claim eligible (one row sinks an independent corpus) | Integration | `…::test_ingested_agent_seeded_cases_are_never_calibration_labels` | RED (xfail) |
| Logfire ingest + reject counters: one span per candidate, one summary span | Integration | `…::test_ingest_emits_ingest_and_reject_counters` | RED (xfail) |
| Ingest defaults to the bank `eval replay-bank` already reads (no new required check) | Unit (structural) | `…::test_ingest_targets_the_structural_bank_by_default` | RED (xfail) |
| Empty/unknown provenance resolves to tier `none`, not a privileged tier | Unit (green guard) | `…::test_empty_and_unknown_provenance_resolve_to_none_not_a_privileged_tier` | ✅ pass |
| No workflow job runs flywheel ingest as a blocking, credentialed check | CI structural (green guard) | `tests/ci/test_flywheel_ingest_ci.py::test_no_workflow_job_runs_flywheel_ingest_as_a_blocking_check` | ✅ pass |
| The required `eval-gate` check is unchanged and still replays the bank | CI structural (green guard) | `tests/ci/test_flywheel_ingest_ci.py::test_existing_structural_eval_gate_still_replays_the_bank` | ✅ pass |

### Pinned contracts (where the wave plan left a choice)

The wave plan names the deliverable ("ingest production false positives and
human dismissals into versioned bank entries, each carrying an explicit
provenance field") but not the symbols. The suite pins these:

- **`mergecraft.evals.flywheel.FlywheelCandidate`** — one production signal
  proposed for ingest, with `case_id`, `title`, `category`, `failure_mode`,
  `expected_finding`, `expected_decision`, the explicit `provenance: str`
  (default `""`), an optional `adjudication: AdjudicationRecord | None`, and the
  usual case metadata (`recorded_findings`, `run_succeeded`, `trust_tier`,
  `body`, `pr_number`, `run_id`, `author_login`, `author_association`).
- **`Case.label_provenance: str = ""`** — the persisted adjudication provenance
  string, holding the same values the bench rows and `tier_for_provenance`
  already use. The empty default keeps every pre-existing case at tier `none`,
  so no committed corpus row changes meaning.
- **`ingest_flywheel(candidates, *, bank_dir=DEFAULT_BANK_DIR, tracer=None) ->
  FlywheelIngestReport`** — the batch entry point. It never raises for a bad
  candidate: each is accepted or dropped independently.
- **`FlywheelIngestReport`** — `outcomes`, plus `ingested` / `rejected`
  partitions and `ingested_count` / `rejected_count`. **`IngestOutcome`** —
  `case_id`, `ingested`, `reason`, `provenance`, `tier`, `path` (`None` on a
  drop).
- **Refuse/allow rules** — `provenance` must be a recognised string
  (`human`, `jev-adjudicated`, `llm-adjudicated`, `agent-seeded`). `agent-seeded`
  is written with no record; the other three require an `AdjudicationRecord`
  whose `provenance_for(record)` equals the declared string, and `human`
  additionally requires `independence == "independent"`. Everything else is
  dropped, tier `none`.
- **Logfire spans** — one `mergecraft.eval.ingest` point span per candidate
  (`mergecraft.eval.ingest.case_id`, `.provenance`, `.tier`, `.ingested`) and one
  `mergecraft.eval.ingest.summary` span carrying
  `mergecraft.eval.ingest.count` and `mergecraft.eval.ingest.rejected`.

### Red / green inventory at authoring time

Sixteen R5 contracts are RED under non-strict `xfail` markers (reason prefix
`green after R5: `) — all sixteen in `tests/evals/test_flywheel_ingest.py`.
Three are green guards that must stay green: the vocabulary guard
(`…::test_empty_and_unknown_provenance_resolve_to_none_not_a_privileged_tier`)
and the two CI structural guards in `tests/ci/test_flywheel_ingest_ci.py`. No
marker uses `strict=True`. The targeted run at authoring time (trace run.id
`f8c575d3-5a2f-433a-9e6a-8c978fcd25d9`) is **3 passed, 16 xfailed**; the full
`tests/evals tests/ci` run is 1077 passed, 2 skipped, 17 xfailed (the extra
xfail is the pre-existing W9 spun-out marker in
`tests/evals/test_benchmark_publication.py`).

### What this suite does not do

- It does not build a new eval harness or a second bank: it writes through the
  existing `add_case` / `Case` path.
- It does not claim calibration from flywheel labels. Every ingested
  `agent-seeded` row is `none`-tier, and one such row sinks a corpus-wide
  claim.
- It does not make ingest a required PR check; the CI guard asserts the
  opposite and pins that the existing structural gate already covers the bank.

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
uv run pytest tests/evals/test_flywheel_ingest.py tests/ci/test_flywheel_ingest_ci.py -q
uv run pytest tests/evals tests/ci -q -rs
```
