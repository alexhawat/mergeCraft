# PR G4 — complexity reduction (`main()` + 5 analyzer hotspots) — test plan (G4.1)

Wave plan: `.ignorelocal/waves/issues-showcase-readiness-wave-plan.md`, "PR G4 —
`refactor(main): drop main() and the analyzer hotspots below complexity 15`"
Worktree: `mergecraft-gsr-g4-complexity` @ `wave/gsr-g4-complexity`

## Wave type: pure-refactor characterisation (not the usual RED suite)

G4 is a **pure refactor** — `main()` and five analyzer functions get split into
named phases/helpers with no behaviour change. Per G4.1's own acceptance line
("8 collected, 8 green before any refactor... and 8 green after"), this suite
inverts the repo's usual RED-first convention: every test below is written to
**pass today, against unmodified code**, and must **stay green** through
G4.2's extraction. A test going red during G4.2 means the refactor changed
behaviour — the wave-plan-executor's contract is to stop and revert, not to
edit these tests. (Per `test-creator`'s own escalation-receiver rule, only
`test-creator` may amend a test, and only when the orchestrator judges the
*test* — not the refactor — to be wrong.)

`RunContext` and `_setup_run` / `_resolve_credentials` / `_execute_agent` /
`_finalize` do not exist pre-G4.2. Two tests
(`test_setup_run_resolves_prompt_and_mode`,
`test_resolve_credentials_matches_current_precedence`) call the real
`resolve_prompt_input` / `resolve_tokens` / `derive_trust_tier` functions
directly, because `tests/support/run_main_harness.py` deliberately stubs
`resolve_prompt_input` and `resolve_tokens` away (see that file's module
docstring) — the harness exists to make `main()`'s *ordering* and *outcome*
testable, not to exercise those two functions' own branches. Every other
test drives the real, current `main()` end to end through that harness.

## Locked decisions this suite pins

| # | Topic | Bound test(s) |
|---|-------|----------------|
| **S1/F6** | Setup-script elapsed time is deducted from the agent's deadline; the deadline covers `_execute_agent` (agent_task) only, not setup/MCP-startup | `test_execute_agent_preserves_deadline_semantics` |
| **S4 fail-closed default** | `derive_trust_tier` defaults to `untrusted` for missing/unrecognised event shapes; only `workflow_dispatch`, same-repo `pull_request`, and maintainer `issue_comment` earn `trusted` | `test_resolve_credentials_matches_current_precedence` |
| **D3** | Six-value `RunOutcome` taxonomy, `MainResult.outcome` set on every return path | `test_main_result_is_unchanged_for_each_run_outcome` |
| G4.2's "**Behaviour-frozen**" note on `_resolve_credentials` | Token brokering precedence (`GH_TOKEN` > job token; App-JWT mint wins when configured, degrades to job token on mint failure; no-token fails closed) | `test_resolve_credentials_matches_current_precedence` |

## Contract → test matrix

### `tests/test_main_phases.py` — 6 tests

| # | Test | Contract | Seam used |
|---|------|----------|-----------|
| 1 | `test_run_context_carries_every_phase_input` | The local-variable sprawl G4.2's `RunContext` will carry — pinned today via `ToolContext`, the one object `main()` already threads every phase's output onto (agent_id/repo/tmpdir from setup; trust_tier/tokens from credentials; resolved_model/mcp_server_url from execute) | Full `main()` run via `run_main_for_test`, asserting on `rec.tool_context` |
| 2 | `test_setup_run_resolves_prompt_and_mode` | `resolve_prompt_input`'s three source branches (`prompt` plain text, `prompt_file`, `prompt` carrying the `~mergecraft` JSON dispatch marker) and the `progress`/mode pair `main()` derives from the result at `main.py:308-313`; `compute_modes`/`_custom_modes` mode computation is independent of the prompt source | Direct calls to `resolve_prompt_input`, `compute_modes`, `_custom_modes` (harness bypasses `resolve_prompt_input`) |
| 3 | `test_resolve_credentials_matches_current_precedence` | Token brokering (`GH_TOKEN` env wins over `INPUT_TOKEN`/`GITHUB_TOKEN`; App-JWT installation-token mint wins when `GITHUB_APP_ID`/`GITHUB_APP_PRIVATE_KEY` are set and degrades to the job token on mint failure; no token anywhere fails closed with `ValueError`) + trust-tier derivation matrix (offline/missing-event/`workflow_dispatch`/`pull_request_target`/fork-PR/same-repo-PR/`issue_comment` by association/unrecognised event — all fail closed to `untrusted` except the four documented `trusted` cases) | Direct calls to `resolve_tokens`, `get_job_token` (via `resolve_tokens`), `derive_trust_tier` |
| 4 | `test_execute_agent_preserves_deadline_semantics` | F6: `asyncio.wait_for`'s deadline wraps the agent coroutine only; a slow-but-within-budget setup script still lets a fast agent complete, and an agent whose own delay is shorter than the *total* run timeout still times out once the setup script's elapsed time is deducted from its budget | Full `main()` run, two scenarios (within-budget / deducted-over-budget) |
| 5 | `test_finalize_runs_on_every_exit_path` | The nested `try`/`finally` in `main()` reaches the publish block (`persist_learnings`/`report_status_checks`/`emit_run_packet`, proxied by `report_status_calls`) and the unconditional `finally` cleanup (`token_ref.aclose()`, `cleanup_temp_directory()`) on all 4 exit shapes: success, agent-reported failure, timeout, and an exception raised after `ToolContext` exists (bad `timeout` input) | Full `main()` run, 4 scenarios |
| 6 | `test_main_result_is_unchanged_for_each_run_outcome` | `MainResult`'s full shape (not just `.outcome`) for each of the six `RunOutcome` values (`run_outcome.py:22-30`). Pins a real, easy-to-miss asymmetry found while authoring this test: `timed_out`/`configuration_error`/`infra_error` reach `main()`'s **outer** `except Exception:` handler, which never calls `emit_run_packet` (`evidence_packet_path` stays `None`); `passed`/`failed`/`inconclusive` return through the normal completion path, where the packet **is** written | Full `main()` run, 6 scenarios |

### `tests/analyzers/test_resolve_complexity.py` — 1 test

| # | Test | Contract |
|---|------|----------|
| 7 | `test_resolve_analyzer_behaviour_unchanged` | `resolve_analyzer`'s (D26) full preference ladder — `declared_unavailable` > `agentsec` special-case > repo-native > type-checker-only-skip (C3/D5) > managed > container > skip — table-driven over the entire bundled catalog (`load_catalog()`, 57 manifests), across 4 scenarios (nothing available / repo-has-tool / managed-only / `allow_repo_binaries=False`). Every scenario forces its booleans explicitly (never `None`) so the expected mode is computed independently from each manifest's own fields, not copied from the function's current output |

### `tests/analyzers/test_registry_complexity.py` — 1 test

| # | Test | Contract |
|---|------|----------|
| 8 | `test_exclusive_group_winner_unchanged` | `_exclusive_group_winner`'s (D26) explicit-override / preference-ladder (`python-lint`, `python-typecheck`, pattern-scanner backend) / alphabetical-tie-break chain, plus `detect_enabled`'s (D22) detect-match → settings-override → exclusive-group-collapse pipeline (same file, same wave — G4.1's own note). The `detect_enabled` scenarios reuse the exact fixture repo + changed-file sets already exercised by `tests/analyzers/test_registry.py`, so they carry independent confidence beyond this new file |

## Status

All 8 tests pass today, against unmodified `main.py` / `analyzers/resolve.py`
/ `analyzers/registry.py`. Verified via:

```
uv run pytest --collect-only -q tests/test_main_phases.py \
  tests/analyzers/test_resolve_complexity.py tests/analyzers/test_registry_complexity.py
# -> 8 tests collected

MERGECRAFT_PYTEST_JOBS=0 uv run pytest -q tests/test_main_phases.py \
  tests/analyzers/test_resolve_complexity.py tests/analyzers/test_registry_complexity.py
# -> 8 passed
```

`make lint` clean on the new files. `make typecheck` is unaffected — it scopes
to `src/mergecraft` only (Makefile:59) and this wave touches no source file.

## G4.2 hand-off note

After the extraction lands, re-run this exact suite unmodified (only import
paths inside the tests may need updating if `resolve_analyzer`/
`_exclusive_group_winner`/`detect_enabled` move — their public names should
not). A regression here that isn't an import-path fix is a behaviour change
the refactor was not supposed to make; stop and revert per G4.1's acceptance
line, don't edit the test.
