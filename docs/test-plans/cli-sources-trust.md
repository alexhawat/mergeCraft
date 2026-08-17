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
- 9 RED (`xfail(strict=False)`)
