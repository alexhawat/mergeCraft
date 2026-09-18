# Test plan — behaviour verification (`tests/verify`)

Trusted-tier CLI that writes a versioned report. Live browsing binds to the
custom browser-use stack (`mergecraft.browser`) plus JEV — not Playwright.
Reviews may consume a fenced report via `--verification-report`.

## Test strategy

Unit tests drive `tests/verify/fake_driver.py` (in-process fake). CLI bind
tests patch `browser_stack_available` or mock `_resolve_driver`. No live
browser runs in `make test` or `make ci`.

## Coverage map

| Area | What it proves | Primary tests |
| --- | --- | --- |
| Schema / contract | Union fields, status vocab, `schema_version` pin | `test_report_schema.py`, `test_union_contract.py`, `test_status_and_blocked.py` |
| Driver seam | Protocol methods against fake; no Playwright import | `test_driver_protocol.py` |
| Browser stack | Fail closed when CDP unreachable or driver unwired (#752) | `test_browser_stack.py`, `test_extra.py` |
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
| `launch_browser_driver` fails closed (#752 gap) | `test_browser_stack.py` |
| Protocol module does not import Playwright | `test_driver_protocol.py::test_protocol_module_does_not_import_playwright` |
| `--artifacts-dir` without stack is not a pass | `test_extra.py::test_cli_artifacts_dir_without_browser_stack_is_not_a_pass` |
| Action failure still writes `report.json` | `test_cli.py::test_cli_action_failure_writes_report_json` |

## Production symbols under test

| Symbol | Module | Tests |
| --- | --- | --- |
| `BrowserStackUnavailableError` / `require_browser_stack` | `mergecraft.verify.extra` | `test_extra.py` |
| `launch_browser_driver` | `mergecraft.browser.launch` | `test_browser_stack.py` |
| `browser_stack_available` | `mergecraft.browser.availability` | `test_browser_stack.py` |
| `_resolve_driver` | `mergecraft.cli.verify_behavior_cmd` | `test_browser_stack.py`, `test_cli.py` |
| `run_verify_behavior` | `mergecraft.verify.runner` | `test_trust_gate.py`, `test_modes_and_inputs.py` |

## Regression guards

Removing the `launch_browser_driver` call from `_resolve_driver` fails
`test_resolve_driver_binds_browser_use_when_available`.

Re-introducing Playwright or `mergecraft[browser]` in `pyproject.toml` fails
`test_playwright_is_not_a_default_or_dev_dependency`.

## Out of scope for unit tests

- Live CDP / Chromium in `make test` or `make ci`
- JEV criterion scoring (follow-on after #752 wires the CDP driver)
