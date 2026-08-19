# Open issues sweep 2026-08-19b — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19b-wave-plan.md`
Worktree: `../mergecraft-issues-sweep-2026-08-19b` @ `wave/issues-sweep-2026-08-19b`
Authoring waves: **W1** (Batch G RED) · **W5** (Batch H RED — xpass inventory) · **W8** (Batch I RED — typing suppressions) · **W10** (Batch J RED — GitLab error string)

W1 pins #277 (xdist flake on grandchild reap) and #278 (`MERGECRAFT_LIVE=1` opt-in)
without changing production code. W5 inventories stale `xfail(strict=False)` xpasses
(#276) and adds the RED `scripts/check_xpass.py` ratchet. W8 inventories `type: ignore`
/ `cast(` under `src/mergecraft/` (#275) and adds the RED `scripts/check_type_ignores.py`
ratchet. W10 pins #279: a GitLab `UnsupportedScmCapability` message must contain
`not available in this release` (xfail until W12). D6-forbidden paths are not
edited; D6 sites are counted then excluded.

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W3** | `test_setup_script_grandchildren_are_reaped` | `green after W3: #277 wait for pid_file before kill clock` | greened in W3 |
| **W4** | `test_live_module_skips_when_mergecraft_live_unset` (6 cases) | `green after W4: MERGECRAFT_LIVE skip gate` | greened in W4 |
| **W7** | `tests/ci/test_xpass_check.py::test_make_xpass_check_is_wired` | `green after W7: make xpass-check ratchet` | greened in W7 |
| **W9** | `tests/ci/test_type_ignores.py::test_allowed_tree_ignores_and_casts_have_reasons` | `green after W9: #275 justify type: ignore / cast reasons` | greened in W9 |
| **W12** | `tests/scm/test_errors.py::test_gitlab_unsupported_capability_names_this_release` | `green after W12: GitLab not available in this release` | pending — today's wording is the capability token (W10 RED) |

**W6 must not promote** the W7 wiring xfail. That test is still failing (no
`make xpass-check`); it is an xfail, not an xpass.

## Contract matrix

### #277 / D12 — grandchild reap without a 0.5s spawn window

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| G277a | Readiness poll is independent of the 0.5s kill clock | unit | happy — file appears at 0.8s | `tests/config/test_setup_script_timeout.py::test_wait_until_exists_does_not_assume_half_second_grace` |
| G277b | Missing readiness file is not ready | unit | edge — never written | `test_wait_until_exists_returns_false_when_file_never_appears` |
| G277c | Reap recording takes an explicit deadline | unit | happy / edge — `sleep 10` still alive after 0.25s | `test_record_pid_reaped_deadline_is_independent_of_wait_or_kill_timeout` |
| G277d | Non-positive reap deadline is rejected | unit | error — `0` / `-1` | `test_record_pid_reaped_rejects_non_positive_deadline` |
| G277e | Kill-before-readiness fails deterministically | functional | error — old timing | `test_setup_script_grandchildren_are_reaped` (greened W3) |

W3 greens G277e by calling `_wait_until_exists(pid_file)` **before** `wait_or_kill_process_group`. Do not mock `kill_process_group`.

### #278 / D8 — live opt-in

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| G278a | Unset / empty / `"0"` → skip, not fail | functional | happy + edge | `tests/ci/test_live_opt_in.py::test_live_module_skips_when_mergecraft_live_unset` |
| G278b | `MERGECRAFT_LIVE=1` + no creds → fail | functional | error (D9 preserved) | `test_live_module_fails_when_flag_set_without_credentials` |

Both live modules are parametrized:

- `tests/integration/test_live_providers.py`
- `tests/integration/test_github_integration.py`

Child pytest runs with credentials stripped so a developer laptop with keys cannot accidentally hit a provider.

## W1.1 note

Deterministic RED, not inspection-only. The grandchild script delays the pid-file write by 1s so `wait_or_kill(..., timeout=0.5)` expires before readiness. Helpers `_wait_until_exists` and `_record_pid_reaped` have no 0.5s default.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- G277 helper units pass; G277e xfail; G278a xfail; G278b pass
- No `src/` edits; no D6 paths

---

## Batch H — xfail hygiene (#276 / D9)

Authoring wave: **W5**. Implementation: **W6** (promote allowed-tree xpasses),
**W7** (`make xpass-check` wiring). Do not edit D6 test files.

### W5.1 inventory (2026-08-19 @ `7e3f5a5`)

Command: `uv run pytest tests -m "not integration" --strict-markers -q --tb=no -rX --randomly-seed=424242 -n auto`

| Bucket | Count |
|--------|-------|
| Total xpassed | **121** |
| Allowed-tree (W6 cleanup) | **113** |
| D6-excluded (count only; do not promote) | **8** |
| xfailed (still failing; not this wave) | 13 |
| passed / skipped | 2989 / 30 |

GF reported 119 xpassed; this W5 run is 121. The extra two are still on the
allowed tree and belong in the cleanup list below. `tests/ci/test_xpass_check.py::test_make_xpass_check_is_wired`
is **xfailed**, not xpassed — leave it for W7.

D6 xpasses (excluded from cleanup; all in `tests/agents/test_codex_custom_provider.py`):

- `test_codex_config_toml_writes_both_indexed_providers`
- `test_codex_config_toml_writes_three_indexed_providers`
- `test_codex_indexed_wins_singleton_ignored`
- `test_codex_partial_indexed_coverage_writes_only_present_providers` (4 params)
- `test_codex_singleton_alone_emits_default_provider_block`

### W5.2 RED ratchet

`scripts/check_xpass.py` parses pytest `-rX` / `-ra` `XPASS nodeid - reason`
lines. `--from-log PATH` is the cheap W7 path; omitting the log runs the unit
suite. Exit 1 when allowed-tree xpass > 0; D6 xpasses are printed in the
counts and ignored. Verified RED on the W5.1 log: exit 1,
`113 allowed-tree xpassed (121 total, 8 D6-excluded)`.

`make xpass-check` is **not** wired (W7). No `Makefile` edit in W5.

### Contract matrix (#276)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| H276a | Script exists | unit | happy | `tests/ci/test_xpass_check.py::test_script_exists` |
| H276b | D6 path set covers the plan's test files | unit | happy | `test_d6_paths_cover_plan_test_files` |
| H276c | Nodeid D6 classification (incl. params) | unit | happy / edge | `test_is_d6_nodeid` |
| H276d | Log parse splits D6 vs allowed | unit | happy | `test_parse_xpass_log_splits_d6_and_allowed` |
| H276e | Empty log is zero xpass | unit | edge | `test_parse_xpass_log_empty_is_zero` |
| H276f | Allowed-tree xpass → exit 1 | unit | error | `test_check_xpass_fails_on_allowed_tree` / `test_main_from_log_exits_one_on_allowed_xpass` |
| H276g | D6-only xpass → exit 0 | unit | edge | `test_check_xpass_ok_when_only_d6_xpasses` |
| H276h | Zero xpass → exit 0 | unit | happy | `test_check_xpass_ok_when_zero_xpasses` |
| H276i | Missing log file → exit 2 | unit | error | `test_main_from_log_missing_file_exits_two` |
| H276j | `make xpass-check` is in the Make graph | integration | happy after W7 | `test_make_xpass_check_is_wired` (xfail until W7) |

### W6 cleanup list (allowed-tree xpasses only)

Remove `xfail(strict=False)` from these 113 nodeids. Keep the test body. Do
not delete tests. Do not touch D6 files.

`tests/agents/test_minimax_routing.py` (74):

- `test_existing_curated_slug_resolution_is_unchanged` — 68 parametrized cases
  (`anthropic/claude-haiku`, `anthropic/claude-opus`, `anthropic/claude-sonnet`,
  `bedrock/byok`, `deepseek/deepseek-chat`, `deepseek/deepseek-flash`,
  `deepseek/deepseek-pro`, `deepseek/deepseek-reasoner`, `google/gemini-flash`,
  `google/gemini-pro`, `moonshotai/kimi-k2`, `nous/deepseek/deepseek-v4-flash`,
  `openai/gpt-5.4`, `openai/gpt-codex-mini`, `openai/gpt-codex`, `openai/gpt-mini`,
  `openai/gpt-pro`, `openai/gpt-terra`, `openai/gpt`, `openai/o3`,
  `opencode-go/glm-5.1`, `opencode-go/kimi-k2`, `opencode/big-pickle`,
  `opencode/claude-haiku`, `opencode/claude-opus`, `opencode/claude-sonnet`,
  `opencode/gemini-flash`, `opencode/gemini-pro`, `opencode/gpt-5-nano`,
  `opencode/gpt-5.4`, `opencode/gpt-codex-mini`, `opencode/gpt-codex`,
  `opencode/gpt-mini`, `opencode/gpt-pro`, `opencode/gpt-terra`, `opencode/gpt`,
  `opencode/kimi-k2`, `opencode/mimo-v2-pro-free`, `opencode/minimax-m2.5-free`,
  `opencode/minimax-m2.5`, `openrouter/claude-haiku`, `openrouter/claude-opus`,
  `openrouter/claude-sonnet`, `openrouter/deepseek-chat`,
  `openrouter/deepseek-flash`, `openrouter/deepseek-pro`,
  `openrouter/gemini-flash`, `openrouter/gemini-pro`, `openrouter/gpt-5.4`,
  `openrouter/gpt-codex-mini`, `openrouter/gpt-codex`, `openrouter/gpt-mini`,
  `openrouter/gpt-pro`, `openrouter/gpt-terra`, `openrouter/gpt`,
  `openrouter/grok`, `openrouter/kimi-k2`, `openrouter/minimax-m2.5`,
  `openrouter/o4-mini`, `tokenhub/deepseek-v4-flash`, `tokenhub/deepseek-v4-pro`,
  `tokenhub/glm-5.2`, `tokenhub/hy3`, `tokenhub/kimi-k3`, `vertex/byok`,
  `xai/grok-code-fast`, `xai/grok-fast`, `xai/grok`)
- `test_minimax_missing_credential_fails_loud[minimax-minimax-m3]`
- `test_minimax_missing_credential_fails_loud[minimax-unknown-model]`
- `test_minimax_raw_passthrough_slug_resolves`
- `test_minimax_routes_via_codex_with_singleton_env`
- `test_minimax_routes_via_indexed_provider_pair`
- `test_minimax_routes_via_opencode_with_singleton_env`

`tests/agents/test_openai_compatible_gateways.py` (6):

- `test_shared_helper_exposes_multi_provider_resolver`
- `test_shared_multi_provider_resolver_drops_partial_pairs`
- `test_shared_multi_provider_resolver_handles_indexed_pairs`
- `test_shared_multi_provider_resolver_indexed_overrides_singleton`
- `test_shared_multi_provider_resolver_preserves_index_gaps`
- `test_shared_multi_provider_resolver_singleton_maps_to_default`

`tests/agents/test_opencode_custom_provider.py` (5):

- `test_opencode_emits_blocks_for_non_contiguous_indices`
- `test_opencode_emits_provider_blocks_for_each_indexed_pair`
- `test_opencode_indexed_wins_singleton_ignored`
- `test_opencode_partial_indexed_pair_is_dropped`
- `test_opencode_singleton_alone_emits_default_provider_block`

`tests/cli/test_models_list_minimax.py` (3):

- `test_mergecraft_models_list_minimax_row_does_not_leak_api_key`
- `test_mergecraft_models_list_renders_minimax_row_with_credentials`
- `test_mergecraft_models_list_renders_minimax_row_without_credentials`

`tests/evidence/test_gate_actions.py` (15):

- `test_disagreement_report_groups_by_lane_and_rule`
- `test_disagreement_report_on_match_records_no_disagreement`
- `test_enforce_mode_decision_differs_from_shadow_for_low_risk`
- `test_every_outcome_maps_to_a_named_action`
- `test_new_gates_default_to_shadow`
- `test_numeric_score_never_appears_without_findings_and_decision`
- `test_policy_changed_unread_file_maps_to_request_changes`
- `test_policy_high_risk_migration_maps_to_require_human_review`
- `test_policy_low_risk_passing_maps_to_auto_merge`
- `test_policy_schema_failure_maps_to_block`
- `test_policy_tool_loop_maps_to_require_more_tests`
- `test_record_shadow_prediction_writes_to_disk`
- `test_shadow_mode_records_prediction_without_blocking`
- `test_unknown_action_in_policy_is_rejected`
- `test_unrecognised_gate_mode_falls_back_to_shadow`

`tests/tracing/instrumentation/test_emit_failure.py` (2):

- `test_emit_failure_logs_a_warning`
- `test_emit_failure_never_fails_the_run`

`tests/utils/test_learnings_provenance.py` (8):

- `test_approved_learnings_are_fenced_at_seed_time`
- `test_entry_without_maintainer_provenance_is_quarantined`
- `test_every_learning_entry_carries_provenance`
- `test_fork_pr_injected_learning_text_promotes_nothing`
- `test_influence_listing_names_seeded_entries`
- `test_legacy_autopromote_available_as_optin`
- `test_promotion_requires_explicit_approval_by_default`
- `test_quarantined_entry_never_reaches_reviewer_prompt`

### W6 promotion (2026-08-19)

Removed `xfail(strict=False)` from all **113** allowed-tree xpasses listed
above. Test bodies kept. D6 file untouched. W7 wiring xfail untouched.
`test_emit_failure_logs_a_warning` capture was retargeted to stderr
(`capsys`) so the promotion is a real pass: production emit may reset
loguru handlers, which made a dedicated ``logger.add`` sink
order-dependent.

| Bucket | Count |
|--------|-------|
| Allowed-tree xfail markers removed | **113** (7 files) |
| D6 leftovers (still `strict=False` xpass) | **8** — `tests/agents/test_codex_custom_provider.py` |
| Allowed-tree still-failing xfails → `strict=True` + `(#276)` | **13** |
| W7 wiring xfail (still `strict=False`) | **1** — `test_make_xpass_check_is_wired` |

W5 recorded 13 still-failing xfails in the unit suite. W6 inspection found
those 13 plus `test_readme_eval_claim_adjacent_to_dated_metrics_and_corpus_commit`
(W9 eval-replay, also still failing). All allowed-path leftovers other
than the W7 wiring test were set `strict=True` with `(#276)` in `reason=`.
No GitHub issue was created (draft-only).

Leftover **failing** xfails (`strict=True`, `#276`), excluding W7:

- `tests/cli/test_auth_nous_cmd.py::test_auth_nous_fails_closed_when_gh_is_unauthenticated`
- `tests/evals/test_benchmark_publication.py::test_readme_eval_claim_adjacent_to_dated_metrics_and_corpus_commit`
- `tests/instructions/test_offline_review_fence.py::test_injected_pr_body_does_not_change_findings`
- `tests/instructions/test_offline_review_fence.py::test_offline_diff_review_fences_commit_messages_and_patch_headers`
- `tests/tracing/instrumentation/test_agent_attempt.py::test_one_agent_attempt_span_for_skipped_entry`
- `tests/tracing/instrumentation/test_analyzer_run.py` (4)
- `tests/tracing/instrumentation/test_span_tree.py::test_span_tree_shape`
- `tests/tracing/instrumentation/test_usage_entries.py::test_usage_entries_aggregation_across_multiple_attempts`
- `tests/tracing/test_trace_id_bridge.py::test_otel_sink_forwards_real_trace_id`
- `tests/utils/test_fence.py::test_forged_close_does_not_escape_fence`

D6 leftovers (do not promote; morning plan owns these):

- `test_codex_config_toml_writes_both_indexed_providers`
- `test_codex_config_toml_writes_three_indexed_providers`
- `test_codex_indexed_wins_singleton_ignored`
- `test_codex_partial_indexed_coverage_writes_only_present_providers` (4 params)
- `test_codex_singleton_alone_emits_default_provider_block`

`scripts/check_xpass.py` should now exit 0 on allowed-tree (D6 xpasses
excluded from the fail condition). `make xpass-check` still unwired (W7).

### Draft follow-up issue (not filed)

**Title:** Remaining strict xfails after #276 xpass promotion

**Body:** After W6 promoted 113 allowed-tree xpasses, 13 allowed-path tests
still fail and are now `xfail(strict=True)` with `(#276)` in `reason=`. They
are leftovers from other programs (tracing W4 instrumentation, fence
B-Final stub/`nonce` contradiction, eval W9 README metrics, auth_nous
CliRunner `SystemExit`). D6 `test_codex_custom_provider.py` xpasses stay
for the morning plan. Do not `gh issue create` until an owner wants a
separate tracker.

### Acceptance (W5)

### Acceptance (W5)

- Inventory recorded (121 total / 113 allowed / 8 D6)
- `scripts/check_xpass.py` exits 1 on the current allowed tree
- Ratchet unit tests pass; Makefile wiring test xfail until W7
- `make lint` + `make typecheck` clean; collection clean
- No Makefile `xpass-check` target; not wired into `ci-static` / `make test`
- No D6 path edits; no xfail promotions (W6)

---

## Batch I — typing suppressions (#275 / D10)

Authoring wave: **W8**. Implementation: **W9** (justify or remove on the allowed
tree; un-xfail W8.1). Do not edit D6 src files. Do not walk `src/` in W8.

### W8.1 inventory (2026-08-19 @ `0d23a67`)

Command: `uv run python scripts/check_type_ignores.py` (script added this wave;
counts below are the live `src/mergecraft/` scan with D6 excluded from the fail
condition). Every ignore already has `[code]` (finding 5). None have a `—`
reason. No `cast(` has a `#` reason on the same or previous line.

| Bucket | Ignores | Casts | Unjustified (fail the reason rule) |
|--------|---------|-------|-------------------------------------|
| Total | **41** | **15** | 56 |
| Allowed-tree (W9 walk) | **39** | **14** | **53** (39 ignores + 14 casts) |
| D6-excluded (count only; do not edit) | **2** | **1** | 3 |

D6 leftovers (morning plan owns these; checker skips them):

- `src/mergecraft/agents/_stream_consumer.py:321` — `type: ignore[assignment]`
- `src/mergecraft/mcp/verdict.py:484` — `type: ignore[arg-type]`
- `src/mergecraft/mcp/verdict.py:255` — `cast(`

Error codes present on the 41 ignores: `arg-type`, `assignment`, `attr-defined`,
`method-assign`, `misc`, `return-value`. Zero bare `type: ignore` without
brackets on either tree.

### W8.1 RED ratchet

`scripts/check_type_ignores.py` scans `src/mergecraft/**/*.py`. A `type: ignore`
must be `type: ignore[<code>]` with a following em-dash (U+2014) reason on the
same line. A `cast(` call needs a `#` reason on the same line or the previous
line. Exit 1 when allowed-tree unjustified count > 0; D6 files are counted in
the summary and ignored. Verified RED on HEAD: exit 1,
`53 allowed-tree unjustified (41 ignores, 15 casts; 3 D6-excluded violations)`.

`make` is **not** wired (not in W8; W9 un-xfails the live-tree test only).
No `Makefile` edit in W8. No `src/` edits.

### Contract matrix (#275)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| I275a | Script exists | unit | happy | `tests/ci/test_type_ignores.py::test_script_exists` |
| I275b | D6 path set covers the plan's src files | unit | happy | `test_d6_paths_cover_plan_src_files` |
| I275c | Path D6 classification (incl. backslash) | unit | happy / edge | `test_is_d6_src` |
| I275d | Ignore needs `[code]` **and** `—` reason | unit | happy / edge / error | `test_type_ignore_reason_rule` |
| I275e | Cast needs `#` reason on same or previous line | unit | happy / edge / error | `test_cast_reason_rule` |
| I275f | D6 unjustified sites → exit 0 | unit | edge | `test_d6_file_without_reason_is_excluded_from_fail` |
| I275g | Allowed-tree missing reason → exit 1 | unit | error | `test_allowed_tree_missing_reason_fails` / `test_main_exits_one_on_allowed_unjustified` |
| I275h | Empty tree → exit 0 | unit | edge | `test_empty_tree_is_zero` |
| I275i | Missing `src/mergecraft` → exit 2 | unit | error | `test_missing_src_tree_exits_two` |
| I275j | Justified ignore + cast → exit 0 | unit | happy | `test_main_exits_zero_when_justified` |
| I275k | Live D6 sites never appear in allowed violations | integration | edge | `test_scan_tree_skips_d6_from_allowed_on_live_src` |
| I275l | Live allowed tree has a reason on every site | functional | happy after W9 | `test_allowed_tree_ignores_and_casts_have_reasons` (xfail until W9) |

W9 must not promote I275l until every allowed-tree ignore/cast is justified or
removed. Do not edit D6 files.

### W9 walk list (allowed-tree only)

**Ignores lacking `—` reason (39):**

- `src/mergecraft/action/inputs.py` (1)
- `src/mergecraft/agents/__init__.py` (1)
- `src/mergecraft/agents/harness_render.py` (1)
- `src/mergecraft/agents/verifier.py` (1)
- `src/mergecraft/analyzers/agentsec/policy.py` (1)
- `src/mergecraft/analyzers/catalog_docs.py` (2)
- `src/mergecraft/analyzers/lockfile.py` (1)
- `src/mergecraft/analyzers/redact.py` (1)
- `src/mergecraft/analyzers/trust.py` (1)
- `src/mergecraft/cli/eval_cmd.py` (1)
- `src/mergecraft/cli/mcp_cmd.py` (1)
- `src/mergecraft/cli/mcp_serve.py` (2)
- `src/mergecraft/cli/profiles.py` (1)
- `src/mergecraft/config/settings.py` (1)
- `src/mergecraft/evidence/emit.py` (1)
- `src/mergecraft/evidence/packet.py` (2)
- `src/mergecraft/main.py` (2)
- `src/mergecraft/mcp/analyzers.py` (1)
- `src/mergecraft/mcp/verification.py` (1)
- `src/mergecraft/offline_review.py` (2)
- `src/mergecraft/prep/node.py` (2)
- `src/mergecraft/utils/activity.py` (4)
- `src/mergecraft/utils/instructions.py` (1)
- `src/mergecraft/utils/learnings.py` (2)
- `src/mergecraft/utils/log.py` (1)
- `src/mergecraft/utils/normalize_env.py` (1)
- `src/mergecraft/utils/status_checks.py` (3)

**Casts lacking a `#` reason (14):**

- `src/mergecraft/analyzers/impact.py` (1)
- `src/mergecraft/analyzers/parsers/trivy_json.py` (1)
- `src/mergecraft/ci/normalize.py` (1)
- `src/mergecraft/ci/providers/__init__.py` (4)
- `src/mergecraft/classify/blast_radius.py` (2)
- `src/mergecraft/context/call_graph.py` (1)
- `src/mergecraft/context/repo_map.py` (1)
- `src/mergecraft/context/symbol_index.py` (1)
- `src/mergecraft/evidence/emit.py` (1)
- `src/mergecraft/utils/payload.py` (1)

HEAD does **not** already have reasons on the allowed tree — do not skip W9.

### Acceptance (W8)

- Inventory recorded (41 ignores / 15 casts; 39+14 allowed unjustified; 2+1 D6)
- `scripts/check_type_ignores.py` exits 1 on the current allowed tree
- Ratchet unit tests pass; live-tree cleanliness test xfail until W9
- `make lint` + `make typecheck` clean; collection clean
- No Makefile target; no `src/` edits; no D6 path edits

---

## Batch J — release docs (#279 / D11, #280 / D7)

Authoring wave: **W10**. Implementation: **W11** (GitHub-only README + distribution),
**W12** (GitLab error wording + draft follow-up), **W13** (SHA-pin verify + Marketplace
gate). Do not edit D6 files. Do not edit README generated sentinel regions. Do not
change `src/mergecraft/scm/errors.py` in W10.

W10 pins the #279 error-string contract. Today's
`UnsupportedScmCapability("get_pr", provider="GitLabScmAdapter")` message is the
capability-token form:

`GitLabScmAdapter does not support capability 'get_pr'; operation was not emulated`

W12 rewrites it so a GitLab call says GitLab support is not available in this
release (D11). The RED test uses `xfail(strict=False)` tagged `green after W12` so
`make ci` on this branch stays green if re-run before W12.

W11 / W13 docs contracts are stubbed here; those waves own the README /
`docs/distribution.md` copy.

### Contract matrix (#279 error string — W10)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| J279a | GitLab `UnsupportedScmCapability` names this release | unit | error — RED until W12 | `tests/scm/test_errors.py::test_gitlab_unsupported_capability_names_this_release` |

Message must contain `not available in this release` (or the exact W12 / D11
string: `GitLab support is not available in this release`). Not a raw
`NotImplementedError`. Not only a capability token.

### Contract matrix (#279 docs — W11 stub)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| J279b | README features + requirements: 0.1.0 is GitHub-only | docs | happy after W11 | *(W11 — outside generated sentinels)* |
| J279c | `docs/distribution.md` Marketplace copy: same GitHub-only sentence | docs | happy after W11 | *(W11)* |

### Contract matrix (#280 docs — W13 stub)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| J280a | README SHA-pin advice links `CONTRIBUTING.md` verify one-liners | docs | happy after W13 | *(W13 — no `slsa-github-generator`, D7)* |
| J280b | `docs/distribution.md` Marketplace checklist gated on existing attestations | docs | happy after W13 | *(W13 — point at `sign-attest`)* |

### Acceptance (W10)

- J279a collects with zero import errors; xfail until W12 (fails on today's wording)
- `make lint` + `make typecheck` clean
- No `src/` edits; no README / `docs/distribution.md` edits; no D6 path edits
