# Test plan — audit remediation open issues (lane D)

Maps GitHub issues in
[`.ignorelocal/waves/10-audit-remediation-d-open-issues-wave-plan.md`](../../.ignorelocal/waves/10-audit-remediation-d-open-issues-wave-plan.md)
to RED tests authored in **DQ1** (`wave/dq1-issues-red`).

## Issue → test mapping

| Issue | Impl wave | Test file(s) | Tests |
| --- | --- | --- | --- |
| [#493](https://github.com/alexhawat/mergeCraft/issues/493) fail-soft short-id render | DQ2 | `tests/analyzers/test_short_id_failsoft.py` | 5 (`xfail` until DQ2) |
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

## DQ1 reconciliation

After each impl wave, remove satisfied `@pytest.mark.xfail(strict=False)` markers from the greened tests only.

## Amendments

| Date | Change |
| --- | --- |
| 2026-08-27 | DQ1 initial RED suite — 27 named contract tests across 8 files |
