# Behaviour verification — test plan

Browser-driven `reproduce` and `verify` for a running app. The report is a
versioned artifact of its own, not a `Finding`. The command is trusted-tier
only and lives behind the optional `mergecraft[browser]` extra. Reviews may
consume a report through `--verification-report`; the report is nonce-fenced
before it reaches any prompt.

CI never launches a live browser. Unit tests drive an in-process fake in
`tests/verify/fake_driver.py`. A real-browser smoke test, if added later, must
be marked `integration` so `make test` excludes it.

## Greening milestones

| Milestone | What lands | Suite |
| --- | --- | --- |
| Report models | Pydantic input/report, derived JSON Schema, markdown view, closed statuses, `blocked` validity | `test_report_schema.py`, `test_union_contract.py`, `test_status_and_blocked.py`, `test_markdown_view.py` |
| Driver seam | `BrowserDriver` protocol, optional-extra error, cookies / screenshot / console on the protocol | `test_driver_protocol.py`, `test_extra.py` |
| Command | `mergecraft verify-behavior`, trust and `shell: disabled` gates, artifact layout, redaction, process cleanup | `test_trust_gate.py`, `test_modes_and_inputs.py`, `test_artifacts_and_lifecycle.py`, `test_cli.py` |
| Review consume | `--verification-report`, fence-before-prompt, behaviour section, no-report path, blocked surfaced | `test_review_integration.py` |

Controls that are green on `main` today (regression pins, not xfail):

| Contract | Test |
| --- | --- |
| `Finding` field set and `extra="forbid"` unchanged | `test_finding_unchanged.py::test_finding_fields_are_unchanged` |
| `FindingSource` gains no behaviour member | `test_finding_unchanged.py::test_finding_source_gains_no_behavior_value` |
| Importing mergeCraft does not load Playwright | `test_extra.py::test_importing_mergecraft_does_not_require_playwright` |
| Other CLI commands work without the extra | `test_extra.py::test_other_commands_work_without_browser_extra` |
| Review prompt without a report has no behaviour section | `test_review_integration.py::test_offline_prompt_without_report_has_no_behavior_section` |

## Contract matrix

| Contract | Milestone | Primary test(s) |
| --- | --- | --- |
| JSON Schema is derived from the Pydantic report model (same pattern as `findings_output_schema()`) | Report models | `test_report_schema.py::test_report_schema_is_derived_from_models` |
| Fully populated report round-trips, including unicode | Report models | `test_report_schema.py::test_report_round_trips` |
| Unknown fields rejected (`extra="forbid"`) on report and input | Report models | `test_report_schema.py::test_report_rejects_unknown_fields`, `…::test_input_rejects_unknown_fields` |
| `schema_version` required | Report models | `test_report_schema.py::test_report_requires_schema_version` |
| Version pin fails when fields change without a bump | Report models | `test_report_schema.py::test_report_schema_version_is_pinned` |
| `artifacts.video` unused / nullable; `artifacts.trace` nullable | Report models | `test_report_schema.py::test_artifacts_video_and_trace_are_nullable` |
| Union of issues 61, 62, and 63 — every input field | Report models | `test_union_contract.py::test_input_covers_union_field` |
| Union of issues 61, 62, and 63 — every output field | Report models | `test_union_contract.py::test_report_covers_union_field` |
| YAML input (issue 62) loads the same model | Report models | `test_union_contract.py::test_yaml_input_loads_union_fields` |
| Closed status vocabularies (verify / reproduce / per-criterion) | Report models | `test_status_and_blocked.py::test_status_vocabulary_is_closed` |
| Cross-mode statuses rejected | Report models | `test_status_and_blocked.py::test_verify_rejects_reproduce_only_status`, `…::test_reproduce_rejects_verify_only_status` |
| Blocked report with empty `missing` is invalid | Report models | `test_status_and_blocked.py::test_blocked_report_with_empty_missing_is_invalid` |
| `blocked` is never a pass | Report models | `test_status_and_blocked.py::test_blocked_is_not_a_pass` |
| Markdown is a view of the JSON | Report models | `test_markdown_view.py::test_markdown_render_is_a_view_of_the_json` |
| Protocol methods + fake satisfies protocol | Driver seam | `test_driver_protocol.py` |
| Cookies by name; screenshot and console on the protocol | Driver seam | `test_driver_protocol.py::test_cookies_are_set_and_read_by_name`, `…::test_console_messages_are_readable`, `…::test_screenshot_writes_a_file` |
| Protocol module does not import Playwright | Driver seam | `test_driver_protocol.py::test_protocol_module_does_not_import_playwright` |
| Extra-absent error names `mergecraft[browser]` | Driver seam | `test_extra.py::test_require_browser_extra_names_install_extra` |
| CLI names the extra when Playwright is missing | Command | `test_extra.py::test_verify_behavior_cli_errors_when_extra_absent` |
| Untrusted tier (`derive_trust_tier` → `untrusted`) is inert and reports `skipped` | Command | `test_trust_gate.py::test_untrusted_tier_is_inert_and_reports_skipped`, `…::test_pull_request_target_is_inert` |
| Trust guard deletion: startup command must not run | Command | `test_trust_gate.py::test_untrusted_does_not_execute_startup_command` |
| `shell: disabled` is inert on a trusted tier and names `shell` | Command | `test_trust_gate.py::test_shell_disabled_is_inert_even_when_trusted` |
| Config cannot re-enable on untrusted | Command | `test_trust_gate.py::test_config_cannot_reenable_on_untrusted` |
| Verify mode: per-criterion status + evidence paths | Command | `test_modes_and_inputs.py::test_verify_mode_produces_per_criterion_status` |
| Reproduce mode: observed vs expected + closed statuses | Command | `test_modes_and_inputs.py::test_reproduce_mode_reports_observed_versus_expected` |
| Unreachable URL → `blocked` naming the URL | Command | `test_modes_and_inputs.py::test_unreachable_url_yields_blocked_naming_the_url` |
| Missing credentials → `blocked` naming the env var, never `fail` | Command | `test_modes_and_inputs.py::test_missing_credentials_yields_blocked_not_fail` |
| Credential values never appear in the report | Command | `test_modes_and_inputs.py::test_credential_values_never_appear_in_the_report` |
| Concurrent runs sharing one credential record the name only | Command | `test_modes_and_inputs.py::test_concurrent_same_credential_records_name_not_value` |
| Artifact layout: issues/`<n>`/repro, prs/`<n>`/verify, manual/`<timestamp>` | Command | `test_artifacts_and_lifecycle.py` layout tests |
| Artifacts redacted before write; no raw browser log wholesale | Command | `test_artifacts_and_lifecycle.py::test_artifacts_are_redacted_before_write`, `…::test_no_raw_browser_log_is_written_wholesale` |
| Post-auth screenshots pass redaction | Command | `test_artifacts_and_lifecycle.py::test_post_auth_screenshots_are_redacted` |
| App process terminated on success, failure, and blocked | Command | `test_artifacts_and_lifecycle.py::test_app_process_is_terminated_on_every_path` |
| CLI flags: `--mode`, `--base`, `--start-command`, `--url`, `--criteria-file`, `--artifacts-dir`, `--issue-file`, `--input`, `--viewport` | Command | `test_cli.py::test_cli_exposes_issue_61_flags_plus_absorbed_extras` |
| Report is nonce-fenced via `utils/fence.py` before any prompt | Review consume | `test_review_integration.py::test_report_enters_the_prompt_fenced` |
| Review output has a distinct behaviour section | Review consume | `test_review_integration.py::test_review_includes_a_behavior_section` |
| Blocked report is surfaced, not swallowed | Review consume | `test_review_integration.py::test_blocked_report_is_surfaced_not_swallowed` |
| No-report path is unchanged | Review consume | `test_review_integration.py::test_skipped_when_no_report_supplied` plus the green prompt pin |
| Behavioural results are not `Finding`s | Review consume | `test_review_integration.py::test_behavioural_results_do_not_become_findings` |
| Untrusted run neither produces nor consumes a report | Review consume | `test_review_integration.py::test_untrusted_run_neither_produces_nor_consumes_a_report` |
| `diff-review --verification-report` | Review consume | `test_review_integration.py::test_diff_review_accepts_verification_report_flag` |

## Deliverable symbols

| Symbol | Planned module | Test anchor |
| --- | --- | --- |
| `VERIFICATION_SCHEMA_VERSION` | `mergecraft.verify.models` | `test_report_schema.py` |
| `verification_report_schema` | `mergecraft.verify.models` | `test_report_schema.py` |
| `VerificationInput` / `VerificationReport` / `ReportArtifacts` | `mergecraft.verify.models` | `test_report_schema.py`, `test_union_contract.py` |
| `VERIFY_STATUSES` / `REPRODUCE_STATUSES` / `CRITERION_STATUSES` | `mergecraft.verify.models` | `test_status_and_blocked.py` |
| `is_successful` | `mergecraft.verify.models` | `test_status_and_blocked.py` |
| `load_verification_input` | `mergecraft.verify.models` | `test_union_contract.py` |
| `render_verification_markdown` | `mergecraft.verify.models` | `test_markdown_view.py` |
| `BrowserDriver` | `mergecraft.verify.driver` | `test_driver_protocol.py` |
| `BrowserExtraMissingError` / `require_browser_extra` | `mergecraft.verify.extra` | `test_extra.py` |
| `run_verify_behavior` | `mergecraft.verify.runner` | `test_trust_gate.py`, `test_modes_and_inputs.py` |
| `resolve_artifacts_dir` / `redact_screenshot` | `mergecraft.verify.artifacts` | `test_artifacts_and_lifecycle.py` |
| `prepare_verification_report_for_prompt` | `mergecraft.verify.review` | `test_review_integration.py` |
| `render_behavior_section` / `consume_verification_report` | `mergecraft.verify.review` | `test_review_integration.py` |
| `verification_report_to_findings` | `mergecraft.verify.review` | `test_review_integration.py` |
| `verify-behavior` command | `mergecraft.cli` | `test_cli.py` |
| `--verification-report` | `mergecraft.cli.diff_review_cmd` | `test_review_integration.py` |

## Guard deletion

Removing the untrusted-tier check fails
`test_untrusted_does_not_execute_startup_command` (the startup command writes a
sentinel file). Removing the `shell: disabled` check fails
`test_shell_disabled_is_inert_even_when_trusted` the same way.

## Out of scope in this suite

- Live Playwright / Chromium in `make test` or `make ci`
- Video recording
- In-Action browser verification
- Mapping behavioural results into the merge-evidence packet
