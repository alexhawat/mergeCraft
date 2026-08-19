# Open issues sweep 2026-08-19c — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19c-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19c` @ `wave/open-issues-sweep-2026-08-19c`
Authoring wave: **W1** (Batch K RED — #284 / D10)

W1 pins #284: PR install lifecycle scripts must not run in the privileged Action
process when the tree is untrusted. Today `start_installation` sets
`PrepOptions.ignore_scripts` from `ctx.payload.shell == "disabled"` only
(`src/mergecraft/mcp/dependencies.py`). Default `shell: restricted` therefore
still runs `postinstall`. W3 greens the RED rows by following D10.

W1.2: `tests/mcp/test_dependencies_python_skip.py` is **not** edited. It asserts
`ignore_scripts is True` under `shell: disabled` (a subset of D10 that stays
true after W3). The old exclusive coupling is pinned in the sibling below.

Later batches (L–O) get their own RED waves; this doc is Batch K only until
those waves land.

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W3** | `test_start_installation_ignore_scripts_follows_d10[untrusted-restricted]` | `green after W3: ignore_scripts follows trust` | greened |
| **W3** | `test_start_installation_ignore_scripts_follows_d10[untrusted-enabled]` | `green after W3: ignore_scripts follows trust` | greened |
| **W3** | `test_start_installation_untrusted_restricted_does_not_run_postinstall` | `green after W3: ignore_scripts follows trust` | greened |
| **W6** | `test_untrusted_restricted_sandbox_none_omits_shell` | `green after W6: untrusted + sandbox none does not register shell` | pending |

All cross-wave xfails use `strict=False`. Do not use `strict=True` (pytest.ini
has `xfail_strict = true`).

## Contract matrix

### #284 / D10 — `ignore_scripts` follows trust, not only shell

D10 (binding): `ignore_scripts=True` when `trust_tier == "untrusted"` **or**
`shell == "disabled"`. Trusted + `restricted` may still run lifecycle scripts.
Do not change Node/Python prep adapters beyond the flag they already honor.

Fixture: `package.json` with a `postinstall` that writes `SENTINEL`. npm is
stubbed (`shutil.which` + `_run_cmd`) so CI does not need a real Node install;
the stub writes `SENTINEL` unless `--ignore-scripts` is in the npm args.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| K284a | Untrusted + `restricted` → `PrepOptions.ignore_scripts is True` | unit | happy (bug) | `tests/mcp/test_dependencies_ignore_scripts_trust.py::test_start_installation_ignore_scripts_follows_d10[untrusted-restricted]` |
| K284b | Untrusted + `enabled` → `ignore_scripts is True` | unit | edge (D10 is trust **or** disabled) | `…[untrusted-enabled]` |
| K284c | Untrusted + `disabled` → `ignore_scripts is True` | unit | happy (already true today) | `…[untrusted-disabled]` |
| K284d | Trusted + `disabled` → `ignore_scripts is True` | unit | happy (any `shell == disabled`) | `…[trusted-disabled]` |
| K284e | Trusted + `restricted` → `ignore_scripts is False` | unit | control (maintainer tree) | `…[trusted-restricted]` |
| K284f | Trusted + `enabled` → `ignore_scripts is False` | unit | edge | `…[trusted-enabled]` |
| K284g | Untrusted + `restricted` does not create `SENTINEL` via `start_installation` → `run_prep_phase` | functional | happy (bug) | `test_start_installation_untrusted_restricted_does_not_run_postinstall` |
| K284h | Trusted + `restricted` **may** run `postinstall` (`SENTINEL` created) | functional | control | `test_start_installation_trusted_restricted_may_run_postinstall` |
| K284i | `shell == disabled` skips `postinstall` for both trust tiers | functional | happy + edge | `test_start_installation_shell_disabled_skips_postinstall` |
| K284j | `run_prep_phase(PrepOptions(ignore_scripts=True))` does not create `SENTINEL` | functional | adapter control | `test_run_prep_phase_ignore_scripts_skips_postinstall` |
| K284k | `run_prep_phase(PrepOptions(ignore_scripts=False))` does create `SENTINEL` | functional | adapter control | `test_run_prep_phase_without_ignore_scripts_runs_postinstall` |

K284j/K284k pass against current `src/` — W3 must not break node flag plumbing.

## W1.2 note

Do not loosen `tests/mcp/test_dependencies_python_skip.py`. That file's
`test_start_installation_completes_on_python_policy_skip` still requires
`ignore_scripts is True` when `shell: disabled`. After W3 that remains correct.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean
- K284c–f, K284h–k pass today; K284a, K284b, K284g greened in W3
- No `src/` edits; no D6 paths (`mcp/git.py`, `upload.py`, `labels.py`,
  `check_runs.py`, `verdict.py`, `tracing/*`, `cli/diff_review_cmd.py`,
  `analyzers/trust.py`, `mcp/git_guards.py`)

## Batch L — #287 / D11 (W4 RED)

`detect_sandbox_method` returns `"none"` when `CI != "true"`. `build_common_tools`
still registers `shell` / `kill_background` for `shell: restricted`. W6 must not
register those tools when sandbox is `"none"` **and** `trust_tier == "untrusted"`.

Reset `_detected_sandbox` between cases (module global).

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| L287a | `CI` unset / `false` / `0` / empty → `detect_sandbox_method() == "none"` | unit | happy | `tests/mcp/test_shell_sandbox_honesty.py::test_detect_sandbox_method_none_outside_ci` |
| L287b | Cache reset between cases | unit | edge | `test_detect_sandbox_method_cache_resets_between_env` |
| L287c | Untrusted + restricted + `"none"` omits `shell` / `kill_background` | integration | happy (bug) | `test_untrusted_restricted_sandbox_none_omits_shell` (xfail W6) |
| L287d | Trusted + restricted + `"none"` still includes `shell` | integration | control | `test_trusted_restricted_sandbox_none_keeps_shell` |
