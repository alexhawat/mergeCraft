# Test plan — behaviour verification (`tests/verify`)

Trusted-tier CLI that writes a versioned report. Live browsing binds to the
custom browser-use stack (`mergecraft.browser`) plus JEV — not Playwright.
Reviews may consume a fenced report via `--verification-report`.

## Test strategy

Unit tests drive `tests/verify/fake_driver.py` (in-process fake). CLI bind
tests patch `browser_stack_available` or mock `_resolve_driver`. Reachable-CDP
construction uses the in-process `fake_cdp_endpoint` fixture (a local HTTP
server answering the discovery routes) — no real Chrome. JEV seam tests replay
recorded envelopes under `tests/verify/fixtures/transport/`, so CI makes zero
live TypeSafe calls. A failing transport (`TypeSafeAPIError` after exhausted 5xx
retries, or a structured `JevError`) is driven through the real seam and runner
to prove it becomes a named `unverified`, never an escaping exception. No live
browser runs in `make test` or `make ci`; the one
real-Chrome test self-skips with a named CDP reason.

## Coverage map

| Area | What it proves | Primary tests |
| --- | --- | --- |
| Schema / contract | Union fields, status vocab, `schema_version` pin | `test_report_schema.py`, `test_union_contract.py`, `test_status_and_blocked.py` |
| CDP probe | `/json/version` 200 is the only green; URL override; errors are `False` | `test_cdp_availability.py` |
| Driver seam | Protocol methods against fake; no Playwright import | `test_driver_protocol.py` |
| Browser stack | Fail closed when CDP unreachable; live driver when reachable (#752) | `test_browser_stack.py`, `test_extra.py` |
| JEV seam | Criteria and repro judgments; honest skips; no arithmetic in Jev | `test_jev_seam.py` |
| JEV client failure | `TypeSafeAPIError` / `JevError` ⇒ named `unverified`, `partial` report | `test_jev_transport_failure.py` |
| CLI | Flags, fail-closed without stack, `--allow-stub`, YAML input | `test_cli.py` |
| Runner | Trust gate, modes, actions, lifecycle, artifacts | `test_trust_gate.py`, `test_modes_and_inputs.py`, `test_artifacts_and_lifecycle.py` |
| Review consume | Fence, separate section, cache key, untrusted skip | `test_review_integration.py` |
| Finding unchanged | Behavioural results are not `Finding`s | `test_finding_unchanged.py` |
| Markdown view | Renderer is a JSON view | `test_markdown_view.py` |

## Key assertions

| Assertion | Module |
| --- | --- |
| Importing mergeCraft does not load Playwright | `test_extra.py::test_importing_mergecraft_does_not_require_playwright` |
| Playwright is not in `pyproject.toml` | `test_extra.py::test_playwright_is_not_a_default_or_dev_dependency` |
| CLI fails closed when browser stack unavailable | `test_extra.py`, `test_cli.py` |
| `launch_browser_driver` raises with a named endpoint when CDP is unreachable | `test_browser_stack.py` |
| `launch_browser_driver` returns a protocol driver when CDP is reachable | `test_browser_stack.py` |
| Unreachable CDP never yields a `pass` report, even with `--artifacts-dir` | `test_browser_stack.py` |
| A blank page is `unverified` without asking Jev | `test_jev_seam.py` |
| A failed Jev transport is `unverified` (`transport_error`), never an escaping exception | `test_jev_transport_failure.py` |
| A Jev client failure yields a `partial` report, not an aborted run | `test_jev_transport_failure.py` |
| No count/rate name is sent to Jev | `test_jev_seam.py` |
| Protocol module does not import Playwright | `test_driver_protocol.py::test_protocol_module_does_not_import_playwright` |
| `--artifacts-dir` without stack is not a pass | `test_extra.py::test_cli_artifacts_dir_without_browser_stack_is_not_a_pass` |
| Action failure still writes `report.json` | `test_cli.py::test_cli_action_failure_writes_report_json` |

## Production symbols under test

| Symbol | Module | Tests |
| --- | --- | --- |
| `BrowserStackUnavailableError` / `require_browser_stack` | `mergecraft.verify.extra` | `test_extra.py` |
| `launch_browser_driver` | `mergecraft.browser.launch` | `test_browser_stack.py` |
| `browser_stack_available` / `cdp_base_url` | `mergecraft.browser.availability` | `test_cdp_availability.py`, `test_browser_stack.py` |
| `_resolve_driver` | `mergecraft.cli.verify_behavior_cmd` | `test_browser_stack.py`, `test_cli.py` |
| `judge_criteria` / `judge_repro_claim` | `mergecraft.verify.jev_seam` | `test_jev_seam.py` |
| `run_verify_behavior` | `mergecraft.verify.runner` | `test_trust_gate.py`, `test_modes_and_inputs.py` |
| `run_verify_behavior` client-failure composition | `mergecraft.verify.runner` | `test_jev_transport_failure.py` |

## Regression guards

Removing the `launch_browser_driver` call from `_resolve_driver` fails
`test_resolve_driver_binds_live_driver_when_cdp_reachable`.

Removing the `(TypeSafeAPIError, JevError)` catch in `mergecraft.verify.jev_seam`
fails all of `test_jev_transport_failure.py` with the escaping exception rather
than a named `unverified`.

Re-introducing Playwright or `mergecraft[browser]` in `pyproject.toml` fails
`test_playwright_is_not_a_default_or_dev_dependency`.

Re-introducing an unconditional `raise` after a successful CDP probe fails
`test_launch_browser_driver_returns_live_driver_when_cdp_reachable`.

## Out of scope for unit tests

- Live CDP / Chromium in `make test` or `make ci` (the real-Chrome case
  self-skips with a named reason).
- The JEV seam's internal question-pack id and state filtering, beyond the
  "no counting names reach Jev" property.
