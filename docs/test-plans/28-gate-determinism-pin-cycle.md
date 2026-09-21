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
- F3 is greened by the ambient-event guard's own commit: the autouse fixture
  landed in `tests/conftest.py` and all seven guard/probe/opt-in nodes pass.
  The blast-radius enumeration is **zero**, so no test needed an explicit event
  pin; the three-run, zero-change evidence is recorded in the F3 section.
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
| F3 | The autouse guard clears both event variables in a child process | functional | `tests/test_conftest_ambient_event_guard.py::test_autouse_guard_clears_ambient_github_event_in_a_child_process` | no (green — fixture landed) |
| F3 | A cleared default derives fail-closed `untrusted` | unit | `tests/test_conftest_ambient_event_guard.py::test_cleared_default_derives_fail_closed_untrusted` | no (green — fixture landed) |
| F3 | An explicit opt-in still wins over the cleared default | unit | `tests/test_conftest_ambient_event_guard.py::test_explicit_event_opt_in_overrides_the_cleared_default` | no (guards against an over-broad fix) |
| F3 | Both variables are cleared in this process, and the probe child agrees | unit | `tests/probe/test_ambient_event_probe.py` | no (green — fixture landed) |
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
| F13 | A `request_changes` terminal verdict demotes the header table and the record together | unit | `tests/review_record/test_step_summary_reconciliation_775.py::test_header_and_record_agree_on_a_request_changes_terminal_verdict` | no (regression; product fix already applied) |
| F13 | A credential gap demotes the header table and the record together | unit | `tests/review_record/test_step_summary_reconciliation_775.py::test_header_and_record_agree_on_a_credential_gap` | no (regression pin) |
| F13 | A clean success is not demoted | unit | `tests/review_record/test_step_summary_reconciliation_775.py::test_header_and_record_keep_a_clean_success` | no (anti-weakening guard) |
| F13 | A genuine failure is left intact | unit | `tests/review_record/test_step_summary_reconciliation_775.py::test_header_and_record_leave_a_genuine_failure_intact` | no (guard against masking failures) |
| F13 | A `no_verdict` label is left intact | unit | `tests/review_record/test_step_summary_reconciliation_775.py::test_header_and_record_leave_no_verdict_intact` | no (guard against over-broad demotion) |

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

`tests/conftest.py` had no `GITHUB_EVENT_*` guard, so any test reaching
`derive_trust_tier` inherited the runner's event: green on every
`pull_request`, red on the first `push` to `main`. The guard is an autouse
fixture, `_clear_ambient_github_event`, that deletes both variables through
`monkeypatch` before every test. `monkeypatch.setenv` in a test body is the
opt-in and still wins, because the fixture and the test share one
`monkeypatch` instance and the fixture runs first; the original environment is
restored at teardown.

Two artifacts encode the contract:

- `tests/probe/test_ambient_event_probe.py` — a tiny probe that asserts both
  variables are unset, plus an explicit opt-in case. It is run both in the
  main suite and from a child process.
- `tests/test_conftest_ambient_event_guard.py` — runs the probe in a child
  process with `GITHUB_EVENT_NAME=push` and `GITHUB_EVENT_PATH` deliberately
  exported, and requires the child to report three passes. This makes the
  proof independent of the ambient environment of whoever runs the suite.

The explicit-opt-in test sets the variable through `monkeypatch.setenv` after
the guard has run and asserts the trusted tier, so a guard that clobbered a
test's own opt-in would fail.

### Enumeration: zero, recorded

Pinning an event explicitly in the tests the blast-radius enumeration lists is
**vacuous — the list is empty**, and that number is the evidence, not a skipped
step. The operator ran three full-suite passes on the base revision with
randomization disabled so collection was identical across runs, one per ambient
event state: `push`, `pull_request`, and both variables unset (the state the
fixture creates). All three states reported 9309 passed / 0 failed, and all
three `derive_trust_tier` maps were byte-identical — same 179 callers, same
tier per caller, none appearing under one event only. Therefore:

- 0 tests changed behaviour under an ambient event, and
- 0 tests needed an explicit event pin.

The guard still lands, purely preventively. It closes the shape #742 exposed —
a whole-suite ambient-event leak that no pull-request gate can catch by
construction, because the leak only fires on the post-merge push. With the
fixture, CI behaves the way a local checkout already does.

### Explicit-opt-in regression check

The 26 pre-existing test files that set `GITHUB_EVENT_NAME` themselves were run
with the guard active, once with no ambient event and once with
`GITHUB_EVENT_NAME=push` and `GITHUB_EVENT_PATH` exported. Both runs:
**399 passed, 9 skipped** (8 live-credential skips, 1 missing-`meat`-binary
skip) — identical, so no explicit setter regressed and the ambient value no
longer reaches any test process.

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

## F13 — the step-summary header table matches the embedded record

`render_step_summary` renders a coarse header table (`| Outcome | … |`,
`| Diagnostic | … |`) **plus** the embedded deterministic record. It used to
demote the header cells only on a credential gap, so a completed run that
submitted a `request_changes` terminal verdict with no credential degradation
kept `Outcome: success` / `Diagnostic: approved` in the outer table while the
embedded record demoted to `inconclusive` — two postures in one summary. This
was found in review on the change that landed the credential-gap posture.

The fix extracts one shared predicate (`record_is_not_an_approval`) and one
reconciler (`reconcile_outcome`) in `findings/ledger.py`; `step_summary.py`
threads both through. The record's approval-shaped positive is `passed`, the
step table's is `success`, so the reconciler takes a sequence of positives.

`tests/review_record/test_step_summary_reconciliation_775.py` parses the header
table lines and the embedded record lines out of the rendered text and asserts
they agree:

- `request_changes` terminal verdict, no credential gap: both surfaces report
  `inconclusive`, and neither the header `Outcome`/`Diagnostic` nor the record
  `Outcome`/`Verdict diagnostic` lines claim `success`/`approved`.
- credential gap: the same joint demotion.
- clean success: `success` / `approved` in the header and `passed` / `approved`
  in the record are left intact, and `inconclusive` does not appear.
- genuine failure: `failure` / `provider_failure` (header) and `failed` /
  `provider_failure` (record) are left intact — the guard against the
  reconciliation masking a real failure.
- `no_verdict` with no decision: the header `Outcome` stays `no_verdict` and
  the negative diagnostic is untouched.

The suite passes against the fixed tree. Stashing the `step_summary.py` fix
reproduces the exact reported bug (`assert 'success' == 'inconclusive'` on the
first case), so the regression is pinned rather than assumed.

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

## Flake fix: transient egress skip in the CVE fixture

The `osv-scanner` parameter of
`tests/analyzers/test_adapters_supply_chain.py::test_newly_introduced_cve_reported_with_fix_and_transitive_status`
self-skipped on one CI shard when the userspace egress probe
(`unshare --user --map-root-user --net`) failed transiently, while the same
test passed on the other three shards and locally. The fixture helper
`_run_expecting_cve` already retried the transient case, but only `trivy`'s
empty-findings live-DB race. It now retries a transient skip for either tool,
still bounded by `supply_chain._TRIVY_MAX_ATTEMPTS` / `_TRIVY_RETRY_DELAY_S`
and still fixture-only: production scans keep treating empty or skipped
results as final. The caller's `assert not result.skipped` is unchanged, so a
persistent skip still fails.

Regression coverage, both patching `adapters.run_adapter` (no real network or
namespaces):

| Node id | Pins |
|---------|------|
| `tests/analyzers/test_adapters_supply_chain.py::test_run_expecting_cve_retries_a_transient_egress_skip` | first-attempt skip is retried for `osv-scanner` and `trivy` |
| `tests/analyzers/test_adapters_supply_chain.py::test_run_expecting_cve_persistent_skip_still_fails_the_assertion` | retries exhaust and the skip survives to `assert not result.skipped` |
