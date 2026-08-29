# Test plan — audit remediation open issues (lane D)

Maps the lane D audit-remediation issues below to RED tests authored in **DQ1**
(`wave/dq1-issues-red`). The wave plan driving that lane is operator-local and is
not tracked in this repo, so each issue is linked directly instead.

## Issue → test mapping

| Issue | Impl wave | Test file(s) | Tests |
| --- | --- | --- | --- |
| [#493](https://github.com/alexhawat/mergeCraft/issues/493) fail-soft short-id render | DQ2 | `tests/analyzers/test_short_id_failsoft.py` | 5 (3 render-path; 2 strict-path always pass) |
| [#497](https://github.com/alexhawat/mergeCraft/issues/497) cloud_chain fail-closed | DQ3 | `tests/cli/test_provider_cloud_chain_failclosed.py` | 4 (`xfail` on fail-closed cases until DQ3) |
| [#501](https://github.com/alexhawat/mergeCraft/issues/501) getattr tautology calibration | DQ4 | `tests/ci/test_cheat_signature_lint.py` | 4 (`xfail` on fallback-default case until DQ4) |
| [#502](https://github.com/alexhawat/mergeCraft/issues/502) mutation harness plumbing | DQ5 | `tests/ci/test_mutate_decision_modules.py` | 5 |
| [#503](https://github.com/alexhawat/mergeCraft/issues/503) ratchet honesty | DQ6 | `tests/ci/test_coverage_ratchet_honesty.py` | 2 new + 2 existing |
| [#506](https://github.com/alexhawat/mergeCraft/issues/506) ratchet docs (PR-only guard) | DQ6 | — (docs-only; honesty tests pin comparison branch) | — |
| [#507](https://github.com/alexhawat/mergeCraft/issues/507) `_default_base_branch` contract | DQ6 | `tests/ci/test_coverage_ratchet.py` | 4 new |
| [#509](https://github.com/alexhawat/mergeCraft/issues/509) enterprise reset in tracer cache | DQ7 | `tests/tracing/exporters/test_enterprise_reset.py`, `tests/enterprise/test_runtime_enforcement.py` | 3 |

## Contract notes

- **D9 (#493):** render path fail-soft (`place_findings`); export/explain stay strict (`write_findings_json`, `finding_short_id`).
- **D10 (#497):** error names offending label and supported set (`bedrock`, `vertex`); Bedrock/Vertex mappings unchanged.
- **D4 (#501):** `getattr_tautology` stays `error`; legitimate `getattr(..., None) is None` must not match.
- **D7 (#503):** honesty tests assert **which** stderr failure fired (floor comparison vs merge-base error).
- **D15:** do not assert `head < base < floor` implies caused — not covered here.
- **D11 (#509):** OTLP `claim_sink` after `reset_process_tracer_cache` clears leaked `telemetry="off"`; requires `[tracing]` extra (`importorskip`).

## xfail reconciliation log

| Date | Wave | Tests greened (xfail removed) |
| --- | --- | --- |
| 2026-08-27 | DQ2 | `test_non_hex_fingerprint_still_renders`, `test_non_hex_fingerprint_logs_a_warning_with_path_context`, `test_mixed_batch_renders_hex_findings_with_ids_and_others_without` |
| 2026-08-27 | DQ3 (impl branch) | `test_custom_label_does_not_return_bedrock_suffixes`, `test_error_names_the_label_and_the_supported_set` |
| 2026-08-27 | DQ4 (impl branch) | `test_legitimate_fallback_default_assertion_is_not_flagged` |

DQ3/DQ4 xfails remain on `wave/dq1-issues-red` until impl merges to main.

## Amendments

| Date | Change |
| --- | --- |
| 2026-08-27 | DQ1 initial RED suite — 27 named contract tests across 8 files |
| 2026-08-27 | DQ2 xfail reconciliation on dq1-red |
| 2026-08-27 | DQ3/DQ4 xfails reconciled on impl branches only |
