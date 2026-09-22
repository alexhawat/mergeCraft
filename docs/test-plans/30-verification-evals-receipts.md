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
rule. The live path stays silent. The optional keyless job publishes the
recorded corpus and does not run a model; a recording failure fails that job
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
| Ingest writes an `agent-seeded` structural case with its persisted provenance; `tier_for_provenance` reads it back as `none` | Unit / integration | `tests/evals/test_flywheel_ingest.py::test_ingest_writes_an_agent_seeded_case_with_its_provenance` | ✅ pass |
| `human` is written only when the candidate carries an independent adjudication record | Integration | `…::test_ingest_writes_a_human_adjudicated_case_when_the_record_is_independent` | ✅ pass |
| A model adjudicator's label is written at tier `model`, never upgraded | Unit | `…::test_ingest_writes_an_llm_adjudicated_case_at_the_model_tier` | ✅ pass |
| One vocabulary: the persisted string is exactly `provenance_for(record)` | Unit | `…::test_ingest_writes_the_provenance_the_adjudication_module_derives` | ✅ pass |
| Refuse a candidate without provenance; drop it, no file, tier `none` | Unit / error | `…::test_ingest_refuses_a_candidate_without_provenance_and_drops_it` | ✅ pass |
| An unknown provenance string is refused, never privileged | Unit / edge | `…::test_ingest_refuses_an_unknown_provenance_string` | ✅ pass |
| Refuse to mint `human` without an adjudication record (the claim is not independent) | Integration / error | `…::test_ingest_refuses_to_mint_human_without_an_adjudication_record` | ✅ pass |
| Refuse a `human` claim backed by a non-independent (model-tier) record | Integration / error | `…::test_ingest_refuses_a_human_claim_backed_by_a_non_independent_record` | ✅ pass |
| An `agent-seeded` candidate is never silently upgraded to `human` | Unit | `…::test_ingest_never_marks_an_agent_seeded_case_human` | ✅ pass |
| A rejected candidate leaves no case file and reports no path | Unit / error | `…::test_a_rejected_candidate_leaves_no_case_and_no_label` | ✅ pass |
| Fail-closed is per candidate: a bad row does not abort the batch | Integration / error | `…::test_a_rejected_candidate_does_not_abort_the_batch` | ✅ pass |
| An empty candidate list writes nothing and reports zero counters | Unit / edge | `…::test_ingest_of_an_empty_candidate_list_writes_nothing` | ✅ pass |
| Ingested cases join `run_structural_replay` and carry no detection/calibration block | Integration / functional | `…::test_ingested_cases_join_the_structural_replay_bank` | ✅ pass |
| Ingested `agent-seeded` rows never make a calibration claim eligible (one row sinks an independent corpus) | Integration | `…::test_ingested_agent_seeded_cases_are_never_calibration_labels` | ✅ pass |
| Logfire ingest + reject counters: one span per candidate, one summary span | Integration | `…::test_ingest_emits_ingest_and_reject_counters` | ✅ pass |
| Ingest defaults to the bank `eval replay-bank` already reads (no new required check) | Unit (structural) | `…::test_ingest_targets_the_structural_bank_by_default` | ✅ pass |
| `CASE_ID_RE` rejects a trailing newline (`\Z`, not `$`) and accepts a normal id | Unit / edge | `tests/evals/test_flywheel_ingest.py::test_case_id_re_rejects_a_trailing_newline_and_accepts_a_valid_id` | ✅ pass |
| A traversal-shaped `case_id` is refused by `ingest_flywheel` with the named single-line reason, writing nothing anywhere | Integration / error | `…::test_ingest_refuses_a_traversal_case_id_and_writes_nothing` | ✅ pass |
| `FlywheelCandidate` rejects a traversal id at construction | Unit / error | `…::test_candidate_rejects_a_traversal_case_id_at_construction` | ✅ pass |
| A legal id with dots/dashes still ingests and writes (guard against over-blocking) | Unit (green guard) | `…::test_a_valid_case_id_still_ingests_and_writes` | ✅ pass |
| `store.add_case` refuses a post-construction mutated traversal id and writes nothing | Unit / error | `tests/evals/test_store.py::test_add_case_refuses_a_post_construction_traversal_id` | ✅ pass |
| `add_case` still writes a legal id (guard against over-blocking) | Unit (green guard) | `tests/evals/test_store.py::test_add_case_still_writes_a_valid_id` | ✅ pass |
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

### Red / green inventory at reconciliation time

The R5 implementation (`mergecraft.evals.flywheel` and `Case.label_provenance`)
satisfied all sixteen contracts, so the reconciliation run (trace run.id
`f8c575d3-5a2f-433a-9e6a-8c978fcd25d9`) removed all sixteen non-strict `xfail`
markers — every one in `tests/evals/test_flywheel_ingest.py`. All nineteen R5
tests are now real passes (19 passed, 0 xfail, 0 xpass), and the three green
guards stayed green throughout: the vocabulary guard
(`…::test_empty_and_unknown_provenance_resolve_to_none_not_a_privileged_tier`)
and the two CI structural guards in `tests/ci/test_flywheel_ingest_ci.py`.
**Rationale:** the markers were `strict=False` by design, so the implementation
wave made them `XPASS`; the session-level XPASS ratchet (`tests/conftest.py` +
`scripts/check_xpass.py`) cannot go green until the satisfied markers are
removed, and only `test-creator` may edit `tests/`. Removing the markers also
dropped the now-unused `_R5` reason constant and the stale `pytest` import, and
fixed a pre-existing `I001` import-order offense in the default-bank test body
(no assertion changed).

### Review-finding regression — path traversal via `case_id` (#808)

A review of #808 found the id that becomes the case file stem was not
constrained to a filename token: `..` segments or a trailing newline could
escape `bank_dir`. The guards added here are behavioural, not regex reads:

- `FlywheelCandidate` validates `case_id` at construction, and `_classify`
  re-checks before any `Case` is built, so a post-construction mutation
  (`Case` has no `validate_assignment`) is refused with the named single-line
  reason `INVALID_CASE_ID_REASON`.
- `CASE_ID_RE` anchors with `\Z` (not `$`), so `"a\n"` is rejected.
- `store.add_case` re-checks containment against the resolved `bank_dir` as the
  last line of defence.
- The traversal tests assert the real filesystem effect — no `.md` anywhere in
  the sandbox and nothing outside it — rather than only the returned fields.
  The over-blocking guards assert a legal id still writes.

Task 2 of the same review pass lives in `tests/analyzers/test_adapters_supply_chain.py`:
when a persistent supply-chain run is skipped because this runner cannot apply
userspace filtered egress (`unshare --user --map-root-user --net`), the test now
reports a visible, named `pytest.skip` instead of failing. The gate is matched
narrowly (the `egress policy` prefix **and** the namespace marker), and its
narrowness is pinned by `test_other_skips_are_not_excused_by_the_userspace_egress_gate`.

### What this suite does not do

- It does not build a new eval harness or a second bank: it writes through the
  existing `add_case` / `Case` path.
- It does not claim calibration from flywheel labels. Every ingested
  `agent-seeded` row is `none`-tier, and one such row sinks a corpus-wide
  claim.
- It does not make ingest a required PR check; the CI guard asserts the
  opposite and pins that the existing structural gate already covers the bank.

## R6 — CLI JSON schema version (#777)

Wave outcome: `CLI_JSON_SCHEMA_VERSION` is **defined in** `cli/` rather than
aliased from `mergecraft.review.snapshot`, so the CLI JSON payload contract and
the frozen `ReviewSnapshot` contract can move independently. The decoupling
happens **at the same value** (`"1.0.0"`): no payload moves, no consumer sees a
bump, and `review/` still does not import `cli/`. This is a deliberate runtime
no-op — the value is that the *next* payload addition is a one-line decision.

### Contract matrix

| Contract | Layer | Test node(s) | Status |
| --- | --- | --- | --- |
| `CLI_JSON_SCHEMA_VERSION` is a module-level literal assignment in `cli/global_surface.py`, not an alias of the review constant | Unit (structural) | `tests/cli/test_cli_json_schema_version.py::test_cli_json_schema_version_is_assigned_in_global_surface` | 🔴 red (alias) |
| The name is absent from the module's imported bindings (no `from mergecraft.review.snapshot import REVIEW_SCHEMA_VERSION as CLI_JSON_SCHEMA_VERSION`) | Unit (structural) | `…::test_cli_json_schema_version_is_not_an_imported_binding` | 🔴 red (alias) |
| Bumping `REVIEW_SCHEMA_VERSION` does not change what `cli_json_dumps` stamps | Unit / integration | `…::test_mutating_review_schema_version_does_not_move_the_cli_stamp` | ✅ pass (guard) |
| Bumping the CLI constant does not move `REVIEW_SCHEMA_VERSION` | Unit | `…::test_mutating_cli_json_schema_version_does_not_move_the_review_version` | ✅ pass (guard) |
| Both constants hold `"1.0.0"`; no payload moves and no consumer sees a bump | Unit (green guard) | `…::test_both_schema_versions_hold_the_same_value` | ✅ pass |
| `cli_json_dumps` still stamps `"1.0.0"` after decoupling | Unit / integration | `…::test_cli_json_dumps_still_stamps_1_0_0` | ✅ pass |
| No module under `src/mergecraft/review/` imports `mergecraft.cli` (AST walk, every import form) | Structural layering | `…::test_review_package_does_not_import_cli` | ✅ pass (guard) |

The existing literal pin `tests/cli/test_da_protocol_negotiation.py:50`
(`assert CLI_JSON_SCHEMA_VERSION == "1.0.0"`) is left untouched and stays green.

### Pinned contracts (where the wave plan left a choice)

- **Definition site** — the constant must be a **literal** module-level
  assignment in `cli/global_surface.py`. A re-assignment from the review name
  (`CLI_JSON_SCHEMA_VERSION = REVIEW_SCHEMA_VERSION`) is rejected: it would keep
  the two contracts coupled while looking decoupled.
- **Import shape** — the local binding name `CLI_JSON_SCHEMA_VERSION` must not
  appear in the module's imported bindings, in any alias position.
- **Independence** — monkeypatching either constant must not move the other;
  the CLI stamp is read from `cli/`'s own module global at call time.
- **Layering** — the check walks every `*.py` under `src/mergecraft/review/`
  and rejects `from mergecraft.cli …`, `import mergecraft.cli`, and
  `from mergecraft import cli`.

### Red / green inventory at authoring time

Authored RED by `test-creator` (trace run.id
`f8c575d3-5a2f-433a-9e6a-8c978fcd25d9`). The two structural pins are red for
exactly one reason: `cli/global_surface.py:18` still carries
`from mergecraft.review.snapshot import REVIEW_SCHEMA_VERSION as
CLI_JSON_SCHEMA_VERSION`. The five remaining tests are real green guards and
stay green through the decoupling — they assert independence, the shared value,
the unchanged stamp, and the layering rule. The pins are deliberately **not**
`xfail`; the R6 implementation wave greens them in the same wave.

### What this suite does not do

- It does not bump either schema version, and it does not assert a version
  change: the wave is a decoupling at the same value.
- It does not invert the dependency: `review/` must not import `cli/`, and the
  layering test asserts exactly that.
- It does not touch `src/` or the existing literal pin in the DA protocol suite.

## Commands

```bash
make lint
make typecheck
uv run pytest tests/evidence tests/jev --collect-only -q
uv run pytest tests/evidence/test_shadow_second_target.py tests/ci/test_shadow_comparison_job.py -q
uv run pytest tests/evals/test_flywheel_ingest.py tests/ci/test_flywheel_ingest_ci.py -q
uv run pytest tests/evals tests/ci -q -rs
```

# Test plan — CDP driver and JEV seam (reconciled)

The suite for the wave pair that replaces the fail-closed browser placeholder
with a live CDP-backed `BrowserDriver`, then wires `mergecraft.jev` into the
verify path for criterion and repro scoring. Authored RED before the
implementation existed; the driver and seam wave landed, every cross-wave
`xfail` marker has been removed, and these are now real passes.

- **Branch:** `wave/browser-cdp-driver`
- **Suite:** `tests/verify/` (`test_cdp_availability.py`, `test_browser_stack.py`,
  `test_driver_protocol.py`, `test_jev_seam.py`,
  `test_runner_jev_composition.py`, `test_jev_transport_failure.py`)
- **Fixtures:** `tests/verify/fixtures/transport/*.json` (recorded Jev
  envelopes — CI makes zero live TypeSafe calls), `tests/verify/conftest.py`
  (`fake_cdp_endpoint`)

## Pinned seam surface

The plan named the seam but not its symbol, so the RED wave pinned it here and
in `tests/verify/test_jev_seam.py`. The driver/seam wave built exactly this
surface.

| Symbol | Module | Contract |
| --- | --- | --- |
| `judge_criteria` | `mergecraft.verify.jev_seam` | async; `(criteria, *, page_text, client, trust_tier="untrusted")` → `list[CriterionJudgment]`, one entry per criterion |
| `judge_repro_claim` | `mergecraft.verify.jev_seam` | async; `(claim, *, page_text, client, trust_tier="untrusted")` → `ReproJudgment` |
| `CriterionJudgment` | `mergecraft.verify.jev_seam` | fields `criterion: str`, `verdict: Literal["pass","fail","unverified"]`, `reason: str` |
| `ReproJudgment` | `mergecraft.verify.jev_seam` | fields `claim: str`, `verdict: Literal["reproduced","not_reproduced","unverified"]`, `reason: str` |

Wire rules the tests enforce:

- The seam asks Jev **once per criterion** (no batched "here are N criteria,
  tell me the rate"), reads a `NoulAnswer`, and maps the answer to a verdict in
  Python. The pinned answer names are `satisfied` (criteria) and `reproduced`
  (repro), at the default `NOUL_ACT_FLOOR` of `0.5`.
- An empty/blank page is `unverified` **without dispatching to Jev** — Python
  decides, so Jev is never asked to reason about an absent observation.
- A Jev skip is an honest `unverified` carrying the skip token
  (`credential_absent`, `disabled`, `kill_switch`) in `reason`.
- A client failure is `unverified`, never an exception. `TypeSafeAPIError`
  (after the client exhausts its 5xx retries) and the structured `JevError`
  (`invalid_state`, `credential_absent`) are both caught in the seam and
  returned as `unverified` with reason `transport_error`. The criterion loop
  keeps judging — one failing call does not abort the remaining criteria — and
  the runner reports `partial`, so a partial report is always written.
- No rate, count, or aggregate crosses the seam in either direction.

## Coverage map

| Contract | Layer | Primary tests |
| --- | --- | --- |
| CDP base URL default and `MERGECRAFT_CDP_URL` override | unit | `test_cdp_availability.py::test_cdp_base_url_*` |
| `/json/version` HTTP 200 ⇒ stack available (probed URL pinned) | unit | `test_cdp_availability.py::test_browser_stack_available_true_on_json_version_200` |
| non-200, HTTP error, closed port ⇒ unavailable, never raises | unit / edge / error | `test_cdp_availability.py::test_browser_stack_available_false_on_non_200`, `..._on_http_error`, `..._for_closed_port` |
| Unreachable CDP raises `BrowserStackUnavailableError`; message names the endpoint, `--remote-debugging-port`, `MERGECRAFT_CDP_URL` | unit / refusal | `test_browser_stack.py::test_launch_browser_driver_fails_closed_when_cdp_unreachable` |
| Reachable CDP returns a `BrowserDriver` (lazy construction), not a stub | unit / integration | `test_browser_stack.py::test_launch_browser_driver_returns_live_driver_when_cdp_reachable` |
| `_resolve_driver` binds the live driver; stub only via `--allow-stub` | unit / integration | `test_browser_stack.py::test_resolve_driver_*` |
| Fail closed never produces a passing report, even with `--artifacts-dir`; the written report names `cdp_unavailable:` and keeps the `--remote-debugging-port` remedy through `redact_secrets` | functional / CLI / error | `test_browser_stack.py::test_unreachable_cdp_cli_exits_configuration_not_pass`, `::test_unreachable_cdp_artifacts_run_is_never_a_passing_report` |
| Real Chrome end-to-end navigate/extract, skip-gated and named | functional / live | `test_browser_stack.py::test_live_cdp_driver_navigates_and_extracts` |
| Every `BrowserDriver` method exists on the fake and is async | unit | `test_driver_protocol.py::test_fake_exposes_each_protocol_method_as_async` |
| Protocol and fake declare the same method set | unit | `test_driver_protocol.py::test_protocol_method_set_matches_the_fake` |
| Existing protocol behaviours (navigate/click/fill/type/press/scroll/screenshot/cookies/console) | unit | `test_driver_protocol.py::test_fake_navigate_click_fill_type_press_scroll`, `::test_cookies_are_set_and_read_by_name`, `::test_console_messages_are_readable`, `::test_unreachable_url_raises_on_protocol_navigate`, `::test_scroll_defaults_to_no_movement` |
| Seam: one judgment per criterion, criterion name preserved | integration | `test_jev_seam.py::test_judge_criteria_returns_one_judgment_per_criterion` |
| Seam: one Jev call per criterion (never an aggregate ask) | integration / property | `test_jev_seam.py::test_judge_criteria_asks_jev_once_per_criterion` |
| Seam: noul below floor ⇒ fail | integration / edge | `test_jev_seam.py::test_judge_criteria_below_floor_is_fail` |
| Seam: blank page ⇒ unverified without dispatching | edge | `test_jev_seam.py::test_judge_criteria_empty_page_is_unverified_without_dispatching`, `::test_judge_repro_claim_empty_page_is_unverified` |
| Seam: honest skip ⇒ unverified with named reason | error / edge | `test_jev_seam.py::test_judge_criteria_skip_is_unverified_with_named_reason` |
| Seam: repro claim judged | integration | `test_jev_seam.py::test_judge_repro_claim_returns_reproduced_verdict` |
| Jev scores, Python counts: no numeric field on a judgment | property | `test_jev_seam.py::test_judgment_models_carry_no_numeric_rate_or_count` |
| Jev scores, Python counts: no counting symbol in the seam | property | `test_jev_seam.py::test_seam_module_exposes_no_counting_symbol` |
| Jev scores, Python counts: no count/rate name sent to Jev | property | `test_jev_seam.py::test_seam_never_asks_jev_to_count_or_aggregate` |
| Runner composes a scored Jev verdict into the observable report status (verify pass) | integration | `test_runner_jev_composition.py::test_scored_criterion_pass_reaches_report_status` |
| Runner composes a below-floor Jev verdict into `fail` | integration | `test_runner_jev_composition.py::test_scored_criterion_fail_reaches_report_status` |
| Runner composes a scored repro verdict into `reproduced` | integration | `test_runner_jev_composition.py::test_scored_repro_claim_reaches_report_status` |
| Seam: `TypeSafeAPIError` / `JevError` ⇒ one `unverified` per criterion, loop continues | unit / error | `test_jev_transport_failure.py::test_judge_criteria_transport_failure_is_unverified_and_keeps_judging` |
| Seam: repro claim under client failure ⇒ `unverified`, no exception | unit / error | `test_jev_transport_failure.py::test_judge_repro_claim_transport_failure_is_unverified` |
| Runner: client failure ⇒ `partial` with named `transport_error`, never an abort (verify + reproduce) | integration / error | `test_jev_transport_failure.py::test_runner_reports_partial_when_the_jev_transport_fails` |

## Hermetic env and no-op driver detection

Two R7 verification findings tightened the suite without changing any
assertion's meaning:

- **`MERGECRAFT_CDP_URL` is isolated.** The default-URL assertions in
  `test_cdp_availability.py` pin `MERGECRAFT_CDP_URL` with
  `monkeypatch.setenv`, so they cannot inherit the operator/CI value from the
  shell. The autouse `_isolate_github_event_env` fixture deliberately leaves the
  CDP variable alone: the named live test must honour the configured endpoint,
  and its `skipif` probes that same ambient value at collection. The suite passes
  identically under default env and under any ambient value;
  `MERGECRAFT_CDP_URL=http://127.0.0.1:9777` yields `182 passed, 1 skipped`.
- **A protocol-satisfying no-op driver is detected.** The reachable-CDP cases
  (`test_launch_browser_driver_returns_live_driver_when_cdp_reachable`,
  `test_resolve_driver_binds_live_driver_when_cdp_reachable`) now also assert
  `type(driver) is CdpBrowserDriver`. `isinstance` against the protocol and the
  `_StubBrowserDriver` name check both accept an empty class; the concrete-type
  assertion does not, and needs no real Chrome.

## Named-skip report guard (R-D11, R7-F4)

`test_unreachable_cdp_artifacts_run_is_never_a_passing_report` drives the
`verify-behavior` refusal with `--artifacts-dir` and an unreachable
`MERGECRAFT_CDP_URL`, then reads the `report.json` the refusal writes. Beyond
the fail-closed `status != "pass"` assertion it pins two behaviours that were
previously only asserted by prose:

- the first `skipped_or_unverified` entry starts `cdp_unavailable:` — the skip
  is **named**, so a verification that did not happen never renders as one that
  found nothing (R-D11); and
- that reason still carries the literal `--remote-debugging-port` — the
  operator remedy survives `redact_secrets`, which would otherwise redact the
  hyphenated run as secret-shaped. `redact._KNOWN_SAFE_LITERALS` is the
  exact-match allowlist that keeps it, so emptying that set makes this test
  fail (R7-F4).

The report is required to exist, not conditionally inspected, and both
assertions live on the one test that already reaches this path end to end —
rather than in a near-duplicate. Proof the guard bites: with
`redact._KNOWN_SAFE_LITERALS` monkeypatched to `frozenset()` the reason loses
`--remote-debugging-port`; with the reason rewritten to a bare
`verification skipped` it loses `cdp_unavailable:`. Either mutation fails the
assertions.

## Transport-failure guard (review finding)

A review finding required the seam to survive a client failure. Without the
catch, `AsyncJevClient.call()` raises `TypeSafeAPIError` on transport failure
after exhausted 5xx retries and `JevError` for `invalid_state` /
`credential_absent`; the exception escapes the runner and no partial report is
written. `test_jev_transport_failure.py` pins the fix by driving the real seams,
never by inspecting source:

- **Seam, criteria.** A client whose transport raises
  `TypeSafeAPIError(status_code=500, code="server_error")`, and one raising
  `JevError(code="credential_absent")`, each yield one `unverified` judgment per
  criterion with `reason == "transport_error"`. Two criteria are judged in a
  single call, so a failed call that aborted the loop (return instead of append
  + continue) would drop the second judgment.
- **Seam, repro.** The same two failures yield a `ReproJudgment` with
  `verdict == "unverified"` and `reason == "transport_error"`, claim preserved.
- **Runner.** `run_verify_behavior(..., jev_client=<failing client>)` returns
  status `partial` with a `skipped_or_unverified` entry naming `transport_error`,
  in both `verify` and `reproduce` modes. The exception never propagates — the
  tests would error if it did.

The TypeSafe case replays a recorded 500 envelope
(`tests/verify/fixtures/transport/client_transport_error.json`) through
`RecordedTransport`; `JevError` has no recorded envelope form, so that transport
is injected directly. Retry waits are neutralised with
`monkeypatch.setattr("mergecraft.jev.client.DEFAULT_WAIT", wait_none())` so the
suite stays sub-second while still exercising retry exhaustion.

**Proof the guard bites.** With both `except (TypeSafeAPIError, JevError)`
clauses mutated to `except ValueError`, all eight cases fail with the escaping
exception: `TypeSafeAPIError: server_error` for the `typesafe_500` parameter and
`JevError: credential_absent` for the `credential_absent` parameter. Restoring
the catch returns all eight to green.

## Skip policy

Tests that need a real Chrome are gated with

```python
@pytest.mark.skipif(not browser_stack_available(), reason=_CDP_SKIP_REASON)
```

`_CDP_SKIP_REASON` names CDP, the probed URL (`cdp_base_url()/json/version`),
and the fix. The suite runs with `-ra`, so the skip is surfaced in the run
summary — a quiet deselect is not acceptable. Verify with
`uv run pytest -rs tests/verify/test_browser_stack.py`.

## Cross-wave RED inventory — reconciled

The RED suite used non-strict `xfail` for every contract a later wave would
satisfy, because the repo's global `xfail_strict = true` would otherwise turn an
early pass into a hard failure. The session-level xpass ratchet in
`tests/conftest.py` flagged all 14 of them the moment the driver/seam wave
landed, and the markers were then stripped in a `test-creator` reconciliation.

| Marker declarations removed | Test instances | Reason tag | Greens when |
| --- | --- | --- | --- |
| 1 (module-level `pytestmark`) | 11 in `test_jev_seam.py` | verify → Jev criterion/repro seam | driver/seam wave |
| 2 (per-test decorators) | 2 in `test_browser_stack.py` | live CDP driver replaces the placeholder raise | driver/seam wave |
| 1 (per-test decorator) | 1 live CDP case | live CDP driver navigates and extracts | driver/seam wave |

Four `xfail` declarations covering fourteen test instances were removed. Every
assertion is unchanged; only the marker lines came out. The seam module's
`pytest` import was removed with its module-level marker (it had no other use).
Nothing was weakened, and no `xfail` or `skip` was added — a real pass that a
marker would have hidden is now a real pass in the summary.

| Contract now a real pass | Tests |
| --- | --- |
| Reachable CDP returns a live `BrowserDriver`, not a stub | `test_browser_stack.py::test_launch_browser_driver_returns_live_driver_when_cdp_reachable` |
| `_resolve_driver` binds the live driver when CDP is reachable | `test_browser_stack.py::test_resolve_driver_binds_live_driver_when_cdp_reachable` |
| The seam exists and both judges are async | `test_jev_seam.py::test_seam_module_exposes_async_criterion_and_repro_judges` |
| One judgment per criterion, criterion name preserved, one Jev call each | `test_jev_seam.py::test_judge_criteria_returns_one_judgment_per_criterion`, `::test_judge_criteria_asks_jev_once_per_criterion` |
| Below-floor answer is `fail`; honest skip and blank page are `unverified` | `test_jev_seam.py::test_judge_criteria_below_floor_is_fail`, `::test_judge_criteria_skip_is_unverified_with_named_reason`, `::test_judge_criteria_empty_page_is_unverified_without_dispatching`, `::test_judge_repro_claim_empty_page_is_unverified` |
| Repro claim is judged | `test_jev_seam.py::test_judge_repro_claim_returns_reproduced_verdict` |
| No numeric rate/count on a judgment; no counting symbol; no count reaches Jev | `test_jev_seam.py::test_judgment_models_carry_no_numeric_rate_or_count`, `::test_seam_module_exposes_no_counting_symbol`, `::test_seam_never_asks_jev_to_count_or_aggregate` |

The three refusal cases (unreachable raise with the named endpoint, the
`_resolve_driver` raise, and the CLI never a pass) never carried a marker; they
guard the fail-closed contract and stay passing.

**The named CDP skip stays honest.** One live case needs a real Chrome, so
`test_live_cdp_driver_navigates_and_extracts` remains gated with
`@pytest.mark.skipif(not browser_stack_available(), reason=_CDP_SKIP_REASON)`
after its `xfail` was removed. On a host with a reachable endpoint it is a real
pass; without one it reports a **named skip** in the `-rs` summary — never a
quiet deselect. Reconciled state after the R7 fix: `183 passed` on a host with a
reachable Chrome devtools endpoint, or `182 passed, 1 skipped` when the probed
`MERGECRAFT_CDP_URL` is unreachable (this includes the ambient-value proof with
`http://127.0.0.1:9777`), 0 xfail, 0 xpass, and the session xpass ratchet green.

**Evidence.** Reconciliation verified in the driver/seam wave run space:
`mergecraft-dev` · `run.id=af876d36-2968-49bd-919e-af98d0dfa3b4`,
filter `attributes->>'run.id' = 'af876d36-2968-49bd-919e-af98d0dfa3b4'`.

## Out of scope for this suite

- A live TypeSafe call. The seam tests replay recorded envelopes only.
- Booting a browser in `make test` / `make ci`. The one live test self-skips
  without a CDP endpoint and is never silently deselected.
- Asserting the internal question-pack id or state filtering beyond the
  "no counting names" property.
