# CLI sources trust (TS1) — test plan

Wave plan: `.ignorelocal/02-cli-sources-trust-wave-plan.md` (PR TS1)
Worktree: `../mergecraft-cli-sources-trust` @ `wave/cli-sources-trust`
Authoring wave: **TS1.1** (tests-first — this file). Implementation: **TS1.2**.
xfail-reconciliation: **post-TS1.2** (remove `_TS1_2_XFAIL` markers).

TS1 derives a trust tier for CLI-supplied review sources from **provenance** (D2),
not content. An explicit ``--trust`` override exists for operators (D3) but cannot
be set from repo config. Unknown source shapes fail closed to ``untrusted``
(convention 4). The Action path's ``derive_trust_tier`` is unchanged.

Target API (TS1.2):

- ``ReviewSource`` + ``derive_source_trust_tier`` on `src/mergecraft/analyzers/trust.py`
- ``resolve_offline_review_trust_tier`` / ``apply_cli_trust_tier_env`` on
  `src/mergecraft/offline_review.py`
- ``parse_cli_trust_override`` on `src/mergecraft/config/settings.py` (CLI-only; not in
  ``RepoSettings``)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **TS1.2** | `test_local_cwd_checkout_is_trusted` | `green after TS1.2: derive_source_trust_tier` | pending |
| **TS1.2** | `test_path_outside_invocation_root_is_untrusted` | same | pending |
| **TS1.2** | `test_cloned_remote_is_untrusted` | same | pending |
| **TS1.2** | `test_unknown_source_shape_is_untrusted` | same | pending |
| **TS1.2** | `test_explicit_override_is_honoured_and_logged` | same | pending |
| **TS1.2** | `test_override_cannot_be_set_from_repo_config` | same | pending |
| **TS1.2** | `test_tier_reaches_decide_approval` | same | pending |
| **TS1.2** | `test_tier_reaches_analyzer_trust_gate` | same | pending |
| **TS1.2** | `test_tier_reaches_the_trace` | same | pending |

`test_github_action_path_tier_unchanged` has **no** xfail — regression pin on
existing ``derive_trust_tier`` behaviour.

## Contract matrix

| # | Decision / convention | Layer | Scenario | Primary test |
|---|----------------------|-------|----------|--------------|
| TS1.1a | D2 — cwd checkout trusted | unit | ``local_cwd`` under invocation root | `test_local_cwd_checkout_is_trusted` |
| TS1.1b | D2 — outside path untrusted | unit | path not under invocation root | `test_path_outside_invocation_root_is_untrusted` |
| TS1.1c | D2 — cloned remote untrusted | unit | ``cloned_remote`` kind | `test_cloned_remote_is_untrusted` |
| TS1.1d | convention 4 — unknown shape | unit | ``None``, dict, arbitrary object | `test_unknown_source_shape_is_untrusted` |
| TS1.1e | D3 — explicit override | unit | ``trust_override="trusted"`` + warning log | `test_explicit_override_is_honoured_and_logged` |
| TS1.1f | D3 — not from repo config | unit | YAML ``trust:`` ignored; no ``RepoSettings.trust`` | `test_override_cannot_be_set_from_repo_config` |
| TS1.1g | tier → ``decide_approval`` | unit | untrusted + clean run ⇒ never ``success`` | `test_tier_reaches_decide_approval` |
| TS1.1h | tier → analyzer gate | integration | trusted-only manifest skipped | `test_tier_reaches_analyzer_trust_gate` |
| TS1.1i | tier → trace env | integration | ``MERGECRAFT_TRUST_TIER`` + tracer tier | `test_tier_reaches_the_trace` |
| TS1.1j | Action path unchanged | regression | same-repo PR trusted; ``pull_request_target`` untrusted | `test_github_action_path_tier_unchanged` |

## Acceptance (TS1.1)

- 10 tests collected
- 1 passes (`test_github_action_path_tier_unchanged`)
- 9 RED (`xfail(strict=False)`) — **cleared post-TS1.2 (2026-08-17)**

## TS1.2 xfail reconciliation (2026-08-17)

Removed `_TS1_2_XFAIL` from all nine impl-pending tests in
`tests/security/test_source_trust.py`. Suite is 10 real passes (0 xfail).
Updated D3 override test to capture loguru warnings via sink (not stdlib caplog).

## TS2 — untrusted executable config (PR TS2)

Wave plan: `.ignorelocal/02-cli-sources-trust-wave-plan.md` (PR TS2)
Authoring wave: **TS2.1**. Implementation: **TS2.2**.

Target API (TS2.2):

- ``apply_trust_tier_to_repo_settings`` / ``build_executable_config_skip_reason`` on
  `src/mergecraft/config/settings.py`
- Tier filtering wired in `src/mergecraft/main.py` and `src/mergecraft/offline_review.py`

## Contract matrix (TS2)

| # | Decision / convention | Layer | Primary test |
|---|----------------------|-------|--------------|
| TS2.1a | setup_script not executed | integration | `test_untrusted_setup_script_is_not_executed` |
| TS2.1b | prepush_script not executed | unit | `test_untrusted_prepush_script_is_not_executed` |
| TS2.1c | stop_script not executed | unit | `test_untrusted_stop_script_is_not_executed` |
| TS2.1d | staticChecks command dropped | unit | `test_untrusted_static_check_commands_are_dropped` |
| TS2.1e | D4 declarative survives | unit | `test_declarative_config_survives` |
| TS2.1f | drop reason → prompt | integration | `test_drop_reason_is_logged_and_reaches_the_prompt` |
| TS2.1g | trusted regression | integration | `test_trusted_source_still_executes_scripts` |
| TS2.1h | Action tier unchanged | regression | `test_action_path_behaviour_unchanged` |
| TS2.1i | no config tier escalation | integration | `test_config_cannot_escalate_its_own_tier` |

## Acceptance (TS2.1)

- 9 tests collected
- 2 pass (regression pins)
- 7 RED via `xfail(strict=False)` — **cleared post-TS2.2 (2026-08-17)**

## TS2.2 xfail reconciliation (2026-08-17)

Removed impl-pending xfail markers from `tests/security/test_untrusted_config_execution.py`.
Suite is 9 real passes.
