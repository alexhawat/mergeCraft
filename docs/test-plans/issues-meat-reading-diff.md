# Meat reading-diff harness — W1 RED test plan

Wave plan: `.ignorelocal/waves/issues-meat-reading-diff-wave-plan.md`
Worktree: `mergecraft-meat-a-spike` @ `wave/meat-a-spike`
Batch: A (evaluation spike, #60)

This file maps every contract W1.1–W1.8 pins to the test that covers it,
across the smart-coverage matrix (unit / integration / functional;
happy / edge / error). W1 owns the **RED** half of the tests-first pair:
the suite must collect with zero errors and pass `make lint` +
`make typecheck`, with the contract assertions in xfail until W2 lands
`src/mergecraft/utils/meat_harness.py`.

## xfail schedule

| Wave   | Test file | Marker reason prefix |
|--------|-----------|----------------------|
| **W2** | `tests/utils/test_meat_harness.py` | `green after W2:` (every xfail on a contract the harness must satisfy) |

All cross-wave markers use `strict=False` so an early-passing xfail is an
XFAIL → XPASS upgrade, not a hard failure. W2 reconciles by deleting
markers on tests the harness now satisfies.

## Contract → test matrix

| # | Decision / convention | Test (this wave) | Scenario class |
|---|------------------------|------------------|----------------|
| **W1.1** | D11 — `-json` is the wire format | `test_meat_json_output_parses` | happy path (typed parsing of a recorded fixture) |
| **W1.2** | D13 — missing binary is a skip | `test_missing_meat_binary_is_a_skip_not_a_failure` | error handling (binary absent) |
| **W1.3a** | D7 — inert on untrusted tier | `test_meat_is_inert_on_untrusted_tier` | error handling (gate tripped) |
| **W1.3b** | convention 7 — inert when opt-in unset | `test_meat_is_inert_when_opt_in_flag_unset` | error handling (gate tripped) |
| **W1.3c** | D7 — inert when shell is disabled | `test_meat_is_inert_when_shell_disabled` | error handling (gate tripped) |
| **W1.4a** | D8 + convention 6 — raw diff retained on success | `test_raw_diff_is_always_retained_when_harness_succeeds` | happy path |
| **W1.4b** | D8 + convention 6 — raw diff retained on missing-binary skip | `test_raw_diff_is_always_retained_when_meat_binary_missing` | edge case |
| **W1.4c** | D8 + convention 6 — raw diff retained on subprocess failure | `test_raw_diff_is_always_retained_when_meat_subprocess_fails` | error handling |
| **W1.5a** | non-zero exit → raw diff fallback | `test_meat_failure_falls_back_to_raw_diff` | error handling |
| **W1.5b** | malformed JSON → raw diff fallback | `test_meat_malformed_json_falls_back_to_raw_diff` | error handling |
| **W1.6** | bounded timeout — hung meat cannot hang review | `test_meat_invocation_is_bounded_by_a_timeout` | error handling (timeout) |
| **W1.7a** | convention 8 — credential never logged/stored | `test_no_credential_value_is_logged_or_stored` | security / error handling |
| **W1.7b** | convention 8 — both env-var names (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) | `test_no_credential_value_for_any_meat_env_var[...]` (parametrized) | security |
| **W1.8** | convention 5 — no network in `make test`, fake subprocess only | `test_no_network_call_in_unit_tests` | structural |
| **smoke** | module-surface collection | `test_meat_harness_module_is_collectable`, `test_module_collects_with_zero_errors` | structural |

## Per-decision rationale

### D7 — Trust-tier, opt-in, shell-disabled gates (W1.3)

Each gate is enforced in the harness itself (not at the call site) so
every future caller inherits them. Tests place a fake `meat` binary
under `tmp_path` whose stdout would surface as `abridged_diff` if the
gate were broken; the assertions fail loudly then, exactly as the
plan intends for the load-bearing security tests.

### D8 — Raw diff retention (W1.4)

The three `test_raw_diff_is_always_retained_*` tests cover success,
missing-binary, and subprocess-failure branches. They are the
**structural** tests W1.9 calls out: they must pass as soon as the
harness lands with the right result shape, no marker reconciliation
needed at A Final beyond removing the xfail reason.

### Convention 5 — No network in unit tests (W1.8)

The structural guard scans the test file's source for any reference
to `httpx`, `requests`, `urllib`, raw URLs, or `shutil.which("meat")`.
Every non-integration test in this file drives the harness through a
fake subprocess under `tmp_path` or via the missing-binary path —
this assertion guards against a future contributor silently adding a
network call.

### Convention 8 — Credentials by env-var name only (W1.7)

A canary value (`sk-meat-canary-DO-NOT-LEAK-9c41a6`) is placed in the
credential env vars before the harness runs. If the canary ever appears
in any captured log record or on any result attribute, the test fails.
Parametrization over `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` pins the
contract for both names meat reads.

## Coverage matrix summary

- **Layer:** unit only — every test exercises a single contract in
  isolation. Integration coverage (the harness wired into the offline
  `diff-review` path) is owned by W2 / W4.
- **Scenario classes:**
  - happy path: W1.1, W1.4a
  - edge cases: W1.4b, W1.5b (malformed JSON)
  - error handling: W1.2, W1.3a–c, W1.4c, W1.5a, W1.6, W1.7a–b
  - structural: W1.8, the two collection-smoke tests

## Reconciliation plan

After W2 lands `mergecraft.utils.meat_harness`:

1. Drop the `_HARNESS_AVAILABLE = False` branch — `_require_harness()`
   becomes a no-op. The `_FENCE_AVAILABLE` pattern at
   `tests/utils/test_fence.py:43-49` is the prior art.
2. Remove every `pytest.mark.xfail(reason="green after W2: ...", strict=False)`
   marker on tests the harness now satisfies.
3. Keep the structural tests (`test_no_network_call_in_unit_tests`,
   `test_module_collects_with_zero_errors`) — they are property tests
   on the test corpus itself, not on the harness.
4. Update this file's xfail schedule to record the wave that turned
   each xfail green (W2 for this batch).

## Notes

- The test file uses `pytest.MonkeyPatch.context()` per-test to scope
  the fake `meat` binary under `tmp_path`, matching the
  `tests/utils/test_offline_diff.py::git_repo` style.
- `_write_fake_meat(...)` is the local helper for fake-subprocess
  substitution — convention 5 says the harness is "invoked through a
  fake subprocess in every non-integration test"; the helper centralises
  the shape so the tests read like assertions, not plumbing.
- The `derive_trust_tier` import pins the trust-tier shape (D7) so the
  fixture stays in lockstep with the production code — same drift
  guard `tests/utils/test_fence.py:264` uses.
- No `src/` or production-doc edits in this wave; the test plan lives
  at `docs/test-plans/issues-meat-reading-diff.md` and is **not**
  gitignored (verified via `git check-ignore`).
