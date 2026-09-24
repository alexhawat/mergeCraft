# Test plan — The sticky comment's ledger, identity and record

**Wave:** the RED suite (tests-first) + LG5 strictness sweep · branch `wave/ledger-sticky-comment` · base `origin/main` @ `357f3e25`
**Owner:** `test-creator` · **Implementers:** the ledger-survives wave (ledger + snapshot + blank sticky), the one-sticky wave (reuse + author trust), the record-provenance wave
**Trace run:** service `mergecraft-dev` · wave.plan=ledger-sticky-comment · run.id=`d8fccccf-1062-4118-bdc3-5981bbb9181c`

This document maps each contract in the plan's Part 1 (the ledger survives the
final write; a selected sticky is always updated; one sticky and only ours; the
record names who reviewed) and the locked decisions to the tests that pin it.
The suite is **fully green** after the strictness sweep: every cross-wave red
that carried a non-strict `xfail` was greened by LG2–LG4 and the marker removed.
No test is skipped or xfailed to mask a contract, and no assertion was weakened
or deleted to reach green.

Verification commands:

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest <paths> --collect-only -q  # collection diagnostic
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest <paths> -q                 # per-contract run
make lint && make typecheck                                                      # wave verify targets
```

## Contract → test map

| Contract | Layer | Test file / node | LG1 marker | Greened by |
| --- | --- | --- | --- | --- |
| Ledger survives the final write — path A (agent called `report_progress`) | integration | `tests/findings/test_final_upsert_keeps_ledger.py::test_path_a_report_progress_then_record_keeps_ledger` | xfail removed | LG2 |
| Ledger survives the final write — path B (agent never called `report_progress`) | integration | `tests/findings/test_final_upsert_keeps_ledger.py::test_path_b_persist_creates_then_record_keeps_ledger` | xfail removed | LG2 |
| Every writer stores the pre-footer body it posted (create branch) | unit | `tests/mcp/test_report_progress_snapshot.py::test_first_call_stores_the_pre_footer_body` | xfail removed | LG2 |
| Every writer stores the pre-footer body it posted (update branch) | unit | `tests/mcp/test_report_progress_snapshot.py::test_update_call_stores_the_pre_footer_body` | xfail removed | LG2 |
| A selected sticky with a blank body is updated, not duplicated | unit | `tests/findings/test_ledger_persist_blank_sticky.py::test_blank_body_selected_sticky_is_updated_not_duplicated` | xfail removed | LG2 |
| Selection is not widened to blank bodies | unit | `tests/findings/test_ledger_persist_blank_sticky.py::test_a_blank_comment_is_not_selected_as_the_sticky` | no (GREEN guard) | green throughout |
| Marker shape the survival assertions key on | unit | `tests/findings/test_final_upsert_keeps_ledger.py::test_ledger_markers_are_v2_shaped` | no (GREEN guard) | green throughout |
| A later run's first `report_progress` reuses the existing sticky | functional | `tests/mcp/test_report_progress_sticky_reuse.py::test_second_run_first_call_reuses_the_existing_sticky` | xfail removed | LG3 |
| A deliberately deleted comment stays skipped | unit | `tests/mcp/test_report_progress_sticky_reuse.py::test_deleted_progress_comment_still_skips` | no (GREEN guard) | green throughout |
| The plan-comment target is unchanged | unit | `tests/mcp/test_report_progress_sticky_reuse.py::test_target_plan_comment_is_unchanged` | no (GREEN guard) | green throughout |
| A lookup failure still creates and never raises from the tool | unit | `tests/mcp/test_report_progress_sticky_reuse.py::test_lookup_failure_creates_and_does_not_raise` | no (GREEN guard) | green throughout |
| A human comment carrying a ledger marker is not selected | unit | `tests/findings/test_sticky_selection_author.py::test_a_human_comment_with_a_ledger_marker_is_not_selected` | xfail removed | LG3 |
| A bot sticky is selected | unit | `tests/findings/test_sticky_selection_author.py::test_a_bot_sticky_is_selected` | no (GREEN guard) | green throughout |
| Ledger preference holds among bot comments | unit | `tests/findings/test_sticky_selection_author.py::test_ledger_marker_preference_holds_among_bot_comments` | no (GREEN guard) | green throughout |
| `hydrate` ignores a human ledger marker | integration | `tests/findings/test_sticky_selection_author.py::test_hydrate_ignores_a_human_ledger_marker` | xfail removed | LG3 |
| `persist` ignores a human ledger marker | integration | `tests/findings/test_sticky_selection_author.py::test_persist_ignores_a_human_ledger_marker` | xfail removed | LG3 |
| `upsert` ignores a human ledger marker | integration | `tests/findings/test_sticky_selection_author.py::test_upsert_ignores_a_human_ledger_marker` | xfail removed | LG3 |
| `mergecraft findings ledger` ignores a human ledger marker | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_ignores_a_human_comment_with_ledger_markers` | xfail removed | LG3 |
| `mergecraft findings ledger` prefers the bot sticky over a human marker | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_prefers_the_bot_sticky_over_a_human_marker` | xfail removed | LG3 |
| `mergecraft findings ledger` reads a bot sticky | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_reads_a_bot_sticky` | no (GREEN guard) | green throughout |
| `mergecraft findings ledger` is read-only | functional | `tests/cli/test_findings_ledger_cmd.py::test_ledger_command_is_read_only` | no (GREEN guard) | green throughout |
| Skipped slot + recorded verdict names the slot and the verdict's model | unit | `tests/review_record/test_record_reviewer_provenance.py::test_skipped_slot_with_a_recorded_verdict_names_the_model` | xfail removed | LG4 |
| An approval-shaped `Outcome` is still reconciled to `inconclusive` | unit | `tests/review_record/test_record_reviewer_provenance.py::test_a_passed_outcome_is_still_reconciled_to_inconclusive` | no (GREEN guard) | green throughout |
| No recorded verdict keeps the "no credentialed reviewer ran" wording | unit | `tests/review_record/test_record_reviewer_provenance.py::test_no_recorded_verdict_keeps_the_no_reviewer_wording` | no (GREEN guard) | green throughout |

### Scenario classes

* **Happy path** — path A/B both end with a body carrying every v2 marker and
  the learnings delta, and a second-run `hydrate` recovers every record; a later
  run's first `report_progress` updates the existing sticky and pins the
  comment; a bot sticky is read by the CLI.
* **Edge cases** — blank-body sticky, no `report_progress` call at all, a
  deleted comment (`progress_comment is False`), a heading-only bot comment
  beside a marker-carrying bot comment, a human comment that quotes a marker,
  `target_plan_comment=True`.
* **Error handling** — an issue-comment lookup that raises must fall back to a
  create without surfacing as a tool error; a human-owned comment must never be
  written to (no permission error, no lost ledger).

### Decisions applied

* **Every writer snapshots what it posted, and the final upsert re-merges the
  in-memory ledger.** Path A and path B pin both halves: the snapshot keeps the
  learnings delta, the merge keeps records added after the last persist.
* **The final upsert does not re-fetch the live comment.** The tests drive the
  writer's own state; none asserts a second read on the hot path.
* **Interim trust rule: a comment is read only when `user.type == "Bot"`.** The
  selector, `hydrate`, `persist`, `upsert` and the CLI reader each pin the
  human-vs-bot split; the bot guards pin that the rule does not over-reject.
* **Ledger-marker preference stays, applied after the author filter.** The
  preference test uses two bot comments, so it isolates the ordering from the
  trust rule.
* **`report_progress` reuses a trusted sticky; `progress_comment is False`
  still skips; `target_plan_comment` is unchanged.** All three are separate
  tests.
* **A selected sticky is always updated; selection is not widened to blank
  bodies.** The blank-sticky test patches the selector to return a blank body
  and asserts one update / zero creates; the guard test asserts a blank comment
  is not selectable.
* **"No credentialed reviewer ran" only with no typed terminal verdict.** The
  provenance test carries a typed `request_changes` verdict and asserts the
  integrity line names the verdict's model; the guard test carries no verdict and
  asserts the honest wording survives.
* **The integrity note states no outcome.** The provenance test asserts neither
  "no credentialed reviewer ran" nor "inconclusive" appears, while "this record
  is not an approval" stays; the reconciliation guard pins that an
  approval-shaped `Outcome` is still demoted.
* **No `main.py` edit expected.** The publish-path coverage suite
  (`tests/review_record/test_main_publish_coverage.py`) is untouched and green.
* **`mcp/comment.py:29` stays untouched.** No test touches the run URL.

## RED/GREEN counts

LG1 shipped `11 passed, 13 xfailed`; `--runxfail` showed the thirteen real reds.
LG5 removed every one of the thirteen non-strict `xfail` markers once LG2–LG4
greened them, so the suite is now a plain pass — no `xfail`, no `xpass`, and the
XPASS ratchet clears at exit 0:

```text
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" uv run pytest <the seven paths> -q
→ 24 passed
```

Scoped regression run (no unrelated failures, session exit code 0):

```text
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" MERGECRAFT_PYTEST_JOBS=0 \
  uv run pytest tests/findings tests/mcp tests/review_record \
  tests/cli/test_findings_ledger_cmd.py tests/review/test_terminal_verdict_policy.py -q
→ 1306 passed, 1 skipped
```

The thirteen removed markers split as five for the ledger-survives wave, seven
for the one-sticky wave, and one for the record-provenance wave. The green
guards are real passes the implementers did not regress.

## Fixture updates in this wave (test-only)

* `tests/findings/test_ledger.py` — the paginated-lookup fixture now tags its
  comments `user.type == "Bot"`. The test still pins page-2 ledger preference;
  the tag keeps it green under the new author trust rule.
* `tests/cli/test_findings_ledger_cmd.py` — the default fake now tags its
  comment `user.type == "Bot"`, and the reader gained the scripted-comment
  variants above.

## Reconciliation log

Per-implementation-wave marker removal is recorded here. At LG1 the suite was red
by design: thirteen non-strict `xfail` markers named the wave that greens each
one. LG5 is the strictness sweep that removes the markers now satisfied, so the
suite ends fully green with no masked contract.

* **LG2 (ledger survives the last write).** Removed the five markers tagged
  `green after LG2`: `test_final_upsert_keeps_ledger.py` path A and path B,
  `test_report_progress_snapshot.py` create and update branches, and
  `test_ledger_persist_blank_sticky.py`. All now pass.
* **LG3 (one sticky, and only ours).** Removed the seven markers tagged
  `green after LG3`: `test_sticky_selection_author.py` (human-not-selected,
  `hydrate`, `persist`, `upsert`), `test_report_progress_sticky_reuse.py`
  (`test_second_run_first_call_reuses_the_existing_sticky`), and
  `test_findings_ledger_cmd.py` (human-marker ignore, bot-sticky preference).
* **LG4 (the record names who reviewed).** Removed the one marker tagged
  `green after LG4`:
  `test_record_reviewer_provenance.py::test_skipped_slot_with_a_recorded_verdict_names_the_model`.
* **Absence-only tightening (LG5).** Four tests whose only assertions were an
  absence were gated with a positive premise so they cannot pass vacuously
  (the distinguishing-field rule): the human-comment selector test asserts the
  fixture carries a marker before asserting it is not selected; the `hydrate`
  test asserts the human body is marker-shaped and the return is a
  `FindingLedger`; the CLI human-marker test asserts the scripted comment
  carries the marker and the payload schema was emitted; the blank-comment guard
  asserts the fixture bodies are blank. `test_upsert_ignores_a_human_ledger_marker`
  gained a positive assertion that the created bot comment carries the
  deterministic-record marker. No assertion was weakened or deleted.
* **LG-D1 amendment (LG2).** `tests/review/test_terminal_verdict_policy.py::test_existing_review_and_comment_behaviour_unchanged`
  was amended: the progress-comment pin now asserts the LG-D1 snapshot (the
  pre-footer posted body — starts with the argument, carries the hydrated
  `LEDGER_MARKER_V2_PREFIX` marker, excludes the footer) instead of the raw
  argument.
