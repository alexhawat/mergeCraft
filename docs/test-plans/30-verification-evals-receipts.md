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
