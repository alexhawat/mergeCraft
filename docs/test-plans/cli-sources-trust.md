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

## TS3 — clone hardening (PR TS3)

Wave plan: `.ignorelocal/02-cli-sources-trust-wave-plan.md` (PR TS3)
Authoring wave: **TS3.1**. Implementation: **TS3.2**.

Target API (TS3.2):

- ``ReviewSource``, ``AcquiredSource``, ``acquire``, ``validate_clone_url``,
  ``confine_path``, ``filter_confined_paths``, ``cli_analyzer_sandbox_applies`` on
  `src/mergecraft/utils/source_resolve.py`
- Credential scrub + redirect/submodule hardening on `src/mergecraft/mcp/xrepo.py`

## Contract matrix (TS3)

| # | Decision / convention | Layer | Primary test |
|---|----------------------|-------|--------------|
| TS3.1a | scheme allowlist | unit | `test_file_scheme_is_rejected` |
| TS3.1b | SSH rejected | unit | `test_ssh_scheme_is_rejected` |
| TS3.1c | host allowlist | unit | `test_non_allowlisted_host_is_rejected` |
| TS3.1d | no redirects | unit | `test_redirect_chain_is_not_followed` |
| TS3.1e | D5 token not in config | integration | `test_token_never_written_to_git_config` |
| TS3.1f | D5 token not in argv | integration | `test_token_never_appears_in_process_argv` |
| TS3.1g | D6 no submodule recurse | integration | `test_submodules_are_not_recursed_by_default` |
| TS3.1h | D6 size ceiling | integration | `test_clone_size_ceiling_aborts_cleanly` |
| TS3.1i | D6 file-count ceiling | integration | `test_file_count_ceiling_aborts_cleanly` |
| TS3.1j | D7 symlink containment | unit | `test_symlink_escaping_workspace_is_dropped` |
| TS3.1k | D7 diff path containment | unit | `test_diff_path_escaping_workspace_is_dropped` |
| TS3.1l | D10 clear auth error | unit | `test_anonymous_clone_of_private_repo_is_a_clear_error` |
| TS3.1m | sandbox on CLI path | integration | `test_analyzer_sandbox_applies_on_the_cli_path` |

## Acceptance (TS3.1)

- 13 tests collected
- 0 pass; 13 RED via `xfail(strict=False)` — **cleared post-TS3.2 (2026-08-17)**

## TS3.2 xfail reconciliation (2026-08-17)

Removed impl-pending xfail markers from `tests/security/test_clone_hardening.py`.
Suite is 13 real passes.

## TS4 — source resolver (PR TS4)

Wave plan: `.ignorelocal/02-cli-sources-trust-wave-plan.md` (PR TS4)
Authoring wave: **TS4.1**. Implementation: **TS4.2**.

Target API (TS4.2):

- ``SourceResolverSpec``, ``ResolvedWorkspace``, ``resolve_workspace``,
  ``materialize_resolved_diff``, ``resolve_auth_token``, ``parse_commit_range`` on
  `src/mergecraft/utils/source_resolve.py`
- Generalized ``detect_default_base`` / ``git_merge_base_diff`` on
  `src/mergecraft/utils/offline_diff.py`
- ``review`` verb + hidden ``diff-review`` alias on `src/mergecraft/cli/`

## Contract matrix (TS4)

| # | Decision / convention | Layer | Primary test |
|---|----------------------|-------|--------------|
| TS4.1a | local path ``--repo`` | integration | `test_local_path_source` |
| TS4.1b | D9 worktree common dir | integration | `test_linked_worktree_resolves_common_dir` |
| TS4.1c | public repo URL | integration | `test_public_repo_url_source` |
| TS4.1d | owner/name shorthand | integration | `test_owner_name_shorthand_source` |
| TS4.1e | private repo + token | integration | `test_private_repo_with_token` |
| TS4.1f | ``--head`` / ``--base`` | integration | `test_head_and_base_refs_select_the_diff` |
| TS4.1g | non-default branch | integration | `test_remote_branch_that_is_not_default` |
| TS4.1h | ``--staged`` | integration | `test_staged_only` |
| TS4.1i | ``--unstaged`` | integration | `test_unstaged_only` |
| TS4.1j | ``--range`` | unit | `test_commit_range` |
| TS4.1k | D10 auth precedence | unit | `test_auth_precedence_order` |
| TS4.1l | D8 Harbor pin | regression | `test_review_alias_diff_review_still_works` |
| TS4.1m | DiffMaterialization unchanged | integration | `test_downstream_pipeline_unchanged` |
| TS4.1n | TS1 cloned tier | integration | `test_cloned_source_reviews_at_untrusted_tier` |

## Acceptance (TS4.1)

- 14 tests collected
- 1 passes (`test_review_alias_diff_review_still_works`)
- 13 RED via `xfail(strict=False)` — **cleared post-TS4.2 (2026-08-17)**

## TS4.2 xfail reconciliation (2026-08-17)

Removed impl-pending xfail markers from `tests/cli/test_source_resolver.py`.
Suite is 14 real passes.

## TS5 — adversarial hostile-repo corpus (PR TS5)

Wave plan: `.ignorelocal/02-cli-sources-trust-wave-plan.md` (PR TS5)
Authoring wave: **TS5.1**. Fixture construction: **TS5.2**.

Fixture: `tests/security/fixtures/hostile-repo/` (built by
`tests/security/fixtures/build_hostile_repo.sh`, auto-built in tests when missing).

## Contract matrix (TS5)

| # | Attack / decision | Layer | Primary test |
|---|-------------------|-------|--------------|
| TS5.1a | TS2 setupScript RCE | integration | `test_hostile_setup_script_does_not_execute` |
| TS5.1b | TS2 staticChecks command | unit | `test_hostile_static_check_command_does_not_execute` |
| TS5.1c | TS3/D7 symlink escape | unit | `test_symlink_to_home_is_not_read` |
| TS5.1d | D8 README injection fenced | integration | `test_prompt_injection_in_readme_is_fenced_not_obeyed` |
| TS5.1e | D8 commit message fenced | unit | `test_prompt_injection_in_commit_message_is_fenced` |
| TS5.1f | TS3/D6 size ceiling | unit | `test_oversized_file_hits_the_ceiling` |
| TS5.1g | TS1/D3 trust escalation | unit | `test_repo_cannot_declare_itself_trusted` |
| TS5.1h | D4 usable third-party review | integration | `test_review_still_produces_a_usable_verdict_on_the_hostile_repo` |

## Acceptance (TS5.1)

- 8 tests collected in `tests/security/test_hostile_corpus.py`
- All green once TS1–TS4 hardening is present and the fixture is built

## CC1 — machine contract (PR CC1)

Wave plan: `.ignorelocal/02-cli-sources-trust-wave-plan.md` (PR CC1)
Authoring wave: **CC1.1**. Implementation: **CC1.2**.

Target API (CC1.2):

- ``RUN_OUTCOME_EXIT_CODE`` / ``exit_code_for_outcome`` on `src/mergecraft/run_outcome.py`
- ``--format text|json|jsonl|sarif`` and ``--agent`` on `src/mergecraft/cli/diff_review_cmd.py`
- ``AGENT_PROTOCOL_VERSION`` + event helpers on `src/mergecraft/cli/agent_protocol.py`
- Agent findings in `src/mergecraft/analyzers/sarif.py`

## Contract matrix (CC1)

| # | Contract | Layer | Primary test |
|---|----------|-------|--------------|
| CC1.1a | clean pass → exit 0 | integration | `test_clean_review_exits_zero` |
| CC1.1b | findings exit distinct | integration | `test_findings_exit_code_distinct_from_clean` |
| CC1.1c | blocked exit distinct | integration | `test_blocked_exit_code_distinct_from_findings` |
| CC1.1d | inconclusive exit | integration | `test_inconclusive_exit_code_distinct` |
| CC1.1e | configuration_error exit | integration | `test_config_error_exit_code` |
| CC1.1f | infra_error exit | integration | `test_infra_error_exit_code` |
| CC1.1g | timed_out exit | integration | `test_timeout_exit_code` |
| CC1.1h | total outcome mapping | unit | `test_every_run_outcome_has_exactly_one_exit_code` |
| CC1.1i | text default format | integration | `test_text_format_default` |
| CC1.1j | ``--json`` schema pin | regression | `test_json_format_matches_existing_findings_schema` |
| CC1.1k | SARIF agent findings | integration | `test_sarif_includes_agent_findings` |
| CC1.1l | jsonl one object per line | integration | `test_jsonl_is_one_object_per_line` |
| CC1.1m | protocol_version on events | integration | `test_events_carry_protocol_version` |
| CC1.1n | event sequence | integration | `test_event_sequence_is_run_started_then_phases_then_verdict_then_finished` |
| CC1.1o | findings before verdict | integration | `test_findings_stream_before_the_verdict` |
| CC1.1p | line-by-line parse | integration | `test_protocol_is_parseable_line_by_line_while_streaming` |

## Acceptance (CC1.1)

- 16 tests collected across `tests/cli/test_exit_codes.py`,
  `tests/cli/test_output_formats.py`, `tests/cli/test_agent_protocol.py`
- 2 pass (regression pins: ``--json`` schema)
- 14 RED via `xfail(strict=False)` — pending CC1.2
