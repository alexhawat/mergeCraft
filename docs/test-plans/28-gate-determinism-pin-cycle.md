# Gate determinism and pin cycle — test plan

Worktree: `../mc-gates` on branch `wave/gate-determinism`.
Authoring wave: the RED wave (tests-first — this file). Greening waves follow.
Owner of `tests/` and this directory: `test-creator`.

This plan covers seven contracts: two test rewrites that replace
flaky/wall-clock assertions with structural ones (F1, F2), an ambient-event
guard for the whole suite (F3), two workflow contracts for the action pin
automation (F4, F5), and the "a review that could not run must not publish a
verdict" posture (F10, F11, F12).

## Status

- `make lint`, `make typecheck`: clean.
- New/changed tests are RED against the current tree except where noted below.
- F1 is greened: `_start_and_probe` was converted to the hold-open form and the
  parallel helper guard passes. F2 was already green and is unchanged.
  Twenty-run repetition evidence is recorded below.
- F8 (the `tests/jev` ordering bug) is **out of scope** here: the operator
  could not reproduce it and refuted the original hypothesis, so no test is
  written for it.

## Contract matrix

| ID | Contract | Layer | Test node id | RED today |
|----|----------|-------|--------------|-----------|
| F1 | Two *simultaneously live* MCP servers never share a port | integration | `tests/mcp/test_xdist_isolation.py::test_parallel_server_starts_have_unique_ports_and_tokens` | no (rewrite is green; implementation is sound) |
| F1 | The parallel helper returns its disposer and leaves the server listening | unit | `tests/mcp/test_xdist_isolation.py::test_parallel_start_helper_holds_servers_open_until_stop` | green (helper converted to the hold-open form) |
| F2 | Broker relays SSE chunks in emitted order, asserted on one monotonic clock | integration | `tests/security/test_credential_broker.py::test_broker_streams_sse_incrementally_to_client` | no (rewrite is green; implementation is sound) |
| F2 | The ordering assertion catches a buffering relay the old constant slipped past | unit | `tests/security/test_credential_broker.py::test_incrementality_assertion_rejects_a_buffering_relay` | no (strength proof; strictness guard) |
| F3 | The autouse guard clears both event variables in a child process | functional | `tests/test_conftest_ambient_event_guard.py::test_autouse_guard_clears_ambient_github_event_in_a_child_process` | **yes** — assertion (child reports 2 failed) |
| F3 | A cleared default derives fail-closed `untrusted` | unit | `tests/test_conftest_ambient_event_guard.py::test_cleared_default_derives_fail_closed_untrusted` | environment-dependent |
| F3 | An explicit opt-in still wins over the cleared default | unit | `tests/test_conftest_ambient_event_guard.py::test_explicit_event_opt_in_overrides_the_cleared_default` | no (guards against an over-broad fix) |
| F4 | `stage=manifest` emits a Conventional-Commit subject <= 72 chars | functional | `tests/workflow/test_bump_action_pin_cycle.py::test_manifest_stage_subject_is_within_the_commit_cap` | **yes** — assertion (111 chars) |
| F4 | `stage=pin` keeps its subject within the cap | functional | `tests/workflow/test_bump_action_pin_cycle.py::test_pin_stage_subject_is_within_the_commit_cap` | no (regression pin) |
| F5 | `stage=pin` never attempts a `git push` | functional | `tests/workflow/test_bump_action_pin_cycle.py::test_pin_stage_does_not_attempt_a_git_push` | **yes** — assertion |
| F5 | `stage=pin` prints the exact local command and the reason | functional | `tests/workflow/test_bump_action_pin_cycle.py::test_pin_stage_prints_the_prepared_local_command` | **yes** — assertion |
| F5 | The workflow header stops claiming the "mechanical half" | doc | `tests/workflow/test_bump_action_pin_cycle.py::test_workflow_header_no_longer_claims_to_automate_p` | **yes** — assertion |
| F10/F11 | A skipped reviewer credential reports `inconclusive`, not approval | unit | `tests/review_record/test_credential_gap_verdict_775.py::test_credential_gap_record_reports_inconclusive_not_approval` | **yes** — assertion |
| F10/F11 | The record names analyzers ran/withheld and reviewer participation | unit | `tests/review_record/test_credential_gap_verdict_775.py::test_credential_gap_record_names_who_participated` | **yes** — assertion |
| F10/F11 | A complete run still reports `passed` and `approved` | unit | `tests/review_record/test_credential_gap_verdict_775.py::test_a_complete_run_still_reports_passed_and_approved` | no (anti-weakening guard) |
| F12 | One record cannot carry `passed`, `approved` and a `request_changes` terminal verdict | unit | `tests/review_record/test_credential_gap_verdict_775.py::test_record_cannot_carry_passed_approved_and_request_changes_at_once` | **yes** — assertion |
| F12 | `passed` cannot sit beside a `request_changes` terminal verdict | unit | `tests/review_record/test_credential_gap_verdict_775.py::test_record_does_not_report_passed_beside_a_request_changes_terminal_verdict` | **yes** — assertion |

## F1 — simultaneous, not sequential, port uniqueness

Original form: `_start_and_probe` ended `finally: stop()`, so the sixteen starts
were near-sequential and each assertion saw released ports. The OS may
legitimately reissue a released ephemeral port, so the failure the test
occasionally reported was the system behaving as documented.

Final form (greened): `_start_and_probe` is the single hold-open helper. It
returns `(port, agent_token, orchestrator_token, stop)` and leaves the server
listening; the caller owns the lifetime. It disposes the server itself only on
an error path, so a failed start cannot leak a port. The property test holds
all sixteen servers open through the assertion, probes each, asserts every port
is still listening at assertion time, checks port and both bearer-token sets for
uniqueness, and stops everything in a `finally`. Token uniqueness is asserted
exactly as before, and the helper's other caller (the OS-assigned-port test)
stops its server in a `finally`.

The guard `..._holds_servers_open_until_stop` pins the helper's return contract
and that the server is still listening when the helper returns, so a future edit
cannot reintroduce the stop-before-return form. It failed while the helper
returned three values after disposing the server; it is green now that the
helper is in the hold-open form, and it is the direct test of the helper the
property test builds on.

## F2 — ordering, not a stopwatch

Current form compares the first client arrival against the constant
`expected_stream_duration * 0.85` (0.51 s) — an observed event against a
constant, which cannot distinguish scheduler noise from a buffering regression.

The rewrite adds an emit-time channel to `StreamingSSEUpstream`
(`chunk_emit_monotonic`, appended in emission order) and parses each
`data: {"chunk": n}` frame out of the client stream, recording its arrival on
the same monotonic clock. The assertion is `client[n] < upstream_emit[n + 1]`
for every observed pair.

The buffering fake is a synthetic timeline where every client arrival lands
after the upstream's later emissions but under the old 0.51 s constant; the
test proves the old rule would have passed it and the new rule rejects it.
This is the strictness proof the "no wider margin" decision requires.

Because the broker under test relays correctly today, the rewritten assertion
is green; F2 is an assertion-strength defect, not a product defect. A future
buffering regression is caught by the ordering relation.

## F3 — the ambient-event guard

`tests/conftest.py` has no `GITHUB_EVENT_*` guard today, so any test reaching
`derive_trust_tier` inherits the runner's event: green on every
`pull_request`, red on the first `push` to `main`.

Two artifacts encode the contract:

- `tests/probe/test_ambient_event_probe.py` — a tiny probe that asserts both
  variables are unset, plus an explicit opt-in case. It is run both in the
  main suite and from a child process.
- `tests/test_conftest_ambient_event_guard.py` — runs the probe in a child
  process with `GITHUB_EVENT_NAME=push` and `GITHUB_EVENT_PATH` deliberately
  exported, and requires the child to report three passes. This makes the RED
  independent of the ambient environment of whoever runs the suite.

The explicit-opt-in test sets the variable through `monkeypatch.setenv` after
the guard has run and asserts the trusted tier, so a guard that clobbered a
test's own opt-in would fail.

Deferred to the guard's own commit: pinning an event explicitly in every test
the operator's blast-radius enumeration lists. That enumeration is still
running and the guard's commit is where its two counts are recorded.

## F4 / F5 — the pin automation says only what it can do

The workflow snippets are executed under stubs (`make` is a no-op; `git`
records its argv and reports a non-quiet diff), with the subject read back out
of `$GITHUB_OUTPUT` and the step output out of `$GITHUB_STEP_SUMMARY`. Nothing
asserts on YAML text.

- F4: the manifest subject currently concatenates the full 64-hex digest onto
  a fixed prefix — 111 characters against the 72-character cap — while the pin
  stage truncates. The test runs the real snippet for both stages.
- F5: the pin stage still runs a push step (`git push origin "$BRANCH"`), which
  GitHub refuses because the pin touches workflow files, and its summary
  advertises `gh pr create` instead of the local command. The tests require no
  push invocation and a summary naming
  `MANIFEST_COMMIT=… RELEASE_BASE_BRANCH=main make action-pin-prepare`.

The header test pins the operator's decision that the "mechanical half" claim
is deleted rather than reworded.

## F10 / F11 / F12 — a review that could not run must not read as one that did

`render_deterministic_review_block` renders three independent inputs — the run
outcome, the verdict diagnostic, and the packet decision — and does not
reconcile them.

- F10/F11: with a credential-degradation line present (no credentialed
  reviewer ran), the record must report `inconclusive`, must not contain
  `Outcome: passed` or `Verdict diagnostic: approved`, must carry the
  degradation line, must state the analyzer ran/withheld summary, and must say
  no credentialed reviewer participated. The exact phrase is matched
  case-insensitively against a small set of wordings, so the greening wave can
  word it naturally.
- F12: one record may not simultaneously show `Outcome: passed`,
  `Verdict diagnostic: approved` and a `request_changes` terminal verdict in
  the decision reason. The pairwise variant (`passed` beside
  `request_changes`) allows any reconciliation direction, which matters
  because the operator left the precedence open pending evidence.

An anti-weakening test asserts that a complete run still reports `passed` and
`approved`, so the posture change cannot demote every run.

## Repetition evidence

Both rewritten tests were run twenty consecutive times each, serialised through
the single-worker path so the measurements are not distorted by parallel
collection:

```bash
for i in $(seq 1 20); do MERGECRAFT_PYTEST_JOBS=0 uv run pytest '<node-id>' -q || echo "FAIL run $i"; done
```

| Node id | Pass count |
|---------|------------|
| `tests/mcp/test_xdist_isolation.py::test_parallel_server_starts_have_unique_ports_and_tokens` | 20/20 |
| `tests/mcp/test_xdist_isolation.py::test_parallel_start_helper_holds_servers_open_until_stop` | 20/20 |
| `tests/security/test_credential_broker.py::test_broker_streams_sse_incrementally_to_client` | 20/20 |

The second row is the parallel-helper guard, kept green as the structural pin on
the helper form; the third is the F2 ordering assertion, which was not modified.

## Notes for the greening waves

- `_start_and_probe` in `tests/mcp/test_xdist_isolation.py` is now the
  hold-open form; this was the only test-side change F1 needed.
- SSE ordering uses one process's monotonic clock and no fixed margin; do not
  reintroduce `expected_stream_duration` into the assertion.
- The credential-gap posture belongs to the record renderer, which is the
  human-readable surface where the operator moved the weight; the GitHub check
  conclusion stays `neutral`.
