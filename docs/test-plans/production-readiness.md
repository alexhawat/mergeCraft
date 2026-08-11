# Production readiness — test plan (W1-RED)

Wave plan: `.ignorelocal/design/plan/production-readiness-wave-plan.md`
Worktree: `mergecraft-production-readiness` @ `feat/production-readiness`
Authoring wave: **W1-RED** (tests-first amendment — the entire suite for plan
waves W1–W12 is authored up front; implementation waves turn it green).

## xfail schedule

All cross-wave markers are **non-strict** (`strict=False`) — the repo sets
`xfail_strict = true` globally, and an impl wave landing early must yield
`XPASS` (non-fatal), never a hard failure.

| Plan wave | Test files | Marker reason prefix | Status |
|-----------|------------|----------------------|--------|
| **W1** (trust ordering) | `tests/security/test_trust_ordering.py`, `tests/security/test_trust_ordering_attacks.py` | *(markers removed 2026-08-11)* | **green** after W1 impl |
| **W2** (credentials) | `tests/security/test_credentials.py`, `tests/security/test_shell_push_matrix.py` (push-policy cells), `tests/utils/test_git_setup.py`, `tests/utils/test_secrets.py` (direct symbol coverage) | *(markers removed 2026-08-11)* | **green** after W2 impl |
| **W3** (containment) | `tests/security/test_containment.py`, `tests/security/test_containment_escapes.py`, `tests/utils/test_workspace.py`, `tests/utils/test_privilege.py` | *(markers removed 2026-08-11)* | **green** after W3 impl |
| **W4** (adversarial proof) | `tests/security/test_shell_push_matrix.py`, `test_credential_theft.py`, `test_containment_escapes.py`, `test_trust_ordering_attacks.py` | *(verify 2026-08-11 — no markers)* | **green** vs W3 tree (gap fills plain) |
| **W5** (RunOutcome) | `tests/test_run_outcome.py`, `tests/cli/test_gha_failure_outputs.py`, `tests/evidence/test_run_packet.py` (`TestActionOutputSurfacing`, retargeted) | *(markers reconciled 2026-08-11 — 10 removed; 3 kept then greened by W6)* | **green** |
| **W6** (config/prep) | `tests/config/test_extra_forbid.py`, `tests/config/test_tracing_tri_state.py`, `tests/config/test_timeout_validation.py` (fail-closed half), `tests/config/test_config_failure_policy.py` (unknown-key half), `tests/prep/test_prep_fail_closed.py` (outcome half), `tests/test_run_outcome.py` (W6.1/W6.3 scenarios) | *(markers reconciled 2026-08-11 — 16 removed / 20 cases)* | **green** after W6 impl |
| **W7/W8** (supply chain) | `tests/security/test_supply_chain.py` | *(W7 + W8 markers removed 2026-08-11)* | **green** after W7/W8 impl |
| **W9** (robustness) | `tests/security/test_process_tree_kill.py`, `tests/utils/test_retry_policy.py` (mutation/wait/cursor halves) | *(markers removed 2026-08-11)* | **green** after W9 impl |
| **W10** (model evidence) | `tests/evidence/test_model_evidence.py` | *(markers removed 2026-08-11)* | **green** after W10 impl |
| **W11** (E2E gate) | `tests/security/test_supply_chain.py` (`test_e2e_workflow_*`, `test_compatibility_matrix_documented`); `tests/utils/test_github.py` (`_default_api_base_url`) | *(markers removed 2026-08-11)* | **green** after W11 impl |
| **W12** (ops) | `tests/action/test_action_yml_contract.py`, `tests/config/test_post_checkout_script_removal.py`, `tests/config/test_settings.py` (D5 field gone), `tests/utils/test_log.py`, `tests/mcp/test_network_namespace.py`, `tests/utils/test_payload.py` (`_normalize_suggest_eval_add`) | *(markers removed 2026-08-11)* | **green** after W12 impl |

### xfail reconciliation log

| Date | Impl wave | Markers removed | Notes |
|------|-----------|-----------------|-------|
| 2026-08-11 | W1 | **5** (`test_trust_ordering.py` ×3, `test_trust_ordering_attacks.py` ×2) | Added direct `setup_script_skip_reason` asserts on skip + trusted-run paths |
| 2026-08-11 | W2 | **13** (`test_credentials.py` ×9, `test_shell_push_matrix.py` ×4) | Askpass content test invokes via `sh` (0o600 non-exec); direct tests for `build_agent_env`, `ALWAYS_STRIP_FROM_AGENT_ENV`, `ACTIVE_PROVIDER_KEY_BY_AGENT`, `cleanup_temp_directory`, `register_created_path` |
| 2026-08-11 | W3 | **8** (`test_containment.py` ×5, `test_containment_escapes.py` ×3) | Direct symbol coverage in `test_workspace.py` + `test_privilege.py`; runtime agent UID≠0 deferred to W11 in-image (host structural `setpriv` asserts only). Unrelated agent-gateway `green after W3:` markers in `tests/agents/` left alone (different program) |
| 2026-08-11 | W4 | **0** (verify-only; no W1–W3 markers remained) | Adversarial proof wave: full `shell x push` matrix coverage confirmed + gap fills; see W4 verification snapshot below |
| 2026-08-11 | W5 (per-impl-wave reconciliation) | **9** — module-level `pytestmark` on `test_run_outcome.py` lifted (6 tests: D3 enum shape ×2, passed/failed/infra_error/timed_out ×4 harness scenarios) + `test_failure_writes_structured_result_output` + `test_evidence_packet_output_parses_as_packet_schema` (fixture bug fixed, see notes) + retargeted `TestActionOutputSurfacing` ×2 (were live non-xfail tests importing the doomed `action`/`entry` module — see notes) | Deliberately kept (4, W6-dependent — see below); new direct-symbol + retargeted-live-path tests added; W5.5 still blocked pending the executor's deletion pass |
| 2026-08-11 | W5.5 (tiny reconciliation, post-deletion) | **1** — `test_gha_failure_outputs.py::test_action_entry_module_is_gone` | W5.5 impl wave deleted `src/mergecraft/action/entry.py`; the test's precondition is satisfied, so the `xfail` marker is lifted and it now passes plain (verified under `--runxfail` beforehand, and now plain per-file run: `1 passed`). No other markers touched. `(2026-08-11 ✅: no-commit-per-C2 — xfail removed, worktree left uncommitted per operator instruction)` |
| 2026-08-11 | W6 (per-impl-wave reconciliation) | **16** decorators / **20** cases — see verification snapshot | Direct symbols: `apply_tracing_overrides`, `_ConfigurationError`, `_warn_unknown_config_keys`; learnings-provenance W6 markers left alone (different program) |
| 2026-08-11 | W7 (per-impl-wave reconciliation) | **6** decorators / **10** cases — see verification snapshot | All W7.1–W7.5 supply-chain markers lifted; W8 (4) + W11 (2) in same file deliberately kept |
| 2026-08-11 | W8 (per-impl-wave reconciliation) | **4** decorators / **5** cases — see verification snapshot | All W8.1/W8.2/W8.4/W8.5 markers lifted; W11 (2) in same file deliberately kept |
| 2026-08-11 | W9 (per-impl-wave reconciliation) | **5** decorators — see verification snapshot | Direct symbols for process_group + retry_policy; `test_gate_actions.py` W9/W10 (other program) kept |
| 2026-08-11 | W10 (per-impl-wave reconciliation) | **4** decorators — see verification snapshot | Direct symbols for `ModelFallbackPolicyError` / `_attach_model_evidence` / `_provider_for_model_evidence`; merge-evidence `test_gate_actions.py` W9/W10 kept |
| 2026-08-11 | W11 (per-impl-wave reconciliation) | **2** decorators — see verification snapshot | E2E workflow + compat-matrix pins lifted; direct `_default_api_base_url` coverage added; W12 markers kept |
| 2026-08-11 | W12 (per-impl-wave reconciliation) | **4** (push `@pytest.mark.xfail` + 3× `_W12_XFAIL` on postCheckout removal; runtime `pytest.xfail` branch in suggest_eval_add also deleted) | Amended `test_settings.py` D5 leftover; direct symbols for log + netns + suggest_eval normalize — see snapshot |

## Test infrastructure

| Piece | Purpose |
|-------|---------|
| `tests/support/run_main_harness.py` | Instrumented `mergecraft.main.main()` runner: scripts GitHub client, agents, setup-script subprocess, trust derivation; records an ordered event log (`MainRunRecord`) so tests assert **call order** and observed env without live services. Knobs: `event_name`/`event_payload`, `settings`, `agent` (FakeAgent), `prep_failure`, `setup_script_rc`, `env`, `cleanup_tmpdir`. |
| `tests/security/conftest.py` | `planted_repo` (real git repo with malicious `post-checkout` hook), `make_tool_ctx` factory (parametrized `shell`/`push`/`signed_commits`), `make_agent_run_ctx`, `no_ci_env` (clears `CI` + the `_detected_sandbox` cache so spawns use plain bash). |
| `FakeAgent` (harness) | Returns a scripted `AgentResult`, raises a scripted exception, or sleeps past the timeout — drives every W5/W6 outcome path. |

## Contract → coverage matrix

### Plan W1 — trust ordering (`#7`, D1) — **green**

| Contract | Layer | Happy / edge / error | Tests |
|----------|-------|----------------------|-------|
| Tier derived from event payload | unit | fork-PR / `pull_request_target` / `workflow_dispatch` / same-repo-PR | `test_trust_ordering.py::test_main_derives_expected_tier_for_event` (plain) |
| `setup_script` skipped on untrusted events | functional | repo-controlled script + untrusted event (error class) | `test_trust_ordering.py::test_setup_script_never_runs_on_untrusted_events`, `test_trust_ordering_attacks.py::test_repo_controlled_setup_script_never_runs_untrusted` (plain) |
| `tool_state.setup_script_skip_reason` set on skip / unset when trusted runs | functional | untrusted records reason string; trusted leaves `None` | same two untrusted tests + `test_setup_script_still_runs_on_trusted_events` / `test_trusted_same_repo_pr_still_executes_full_pipeline` |
| Trust classification precedes `setup_git`/`setup_script`/`resolve_tokens`/installation | functional | ordering asserted via harness event log (edge: ordering, not just presence) | `test_trust_ordering.py::test_trust_classification_precedes_*`, `test_trust_ordering_attacks.py::test_trust_precedes_setup_git_on_untrusted_events` (plain) |
| Trusted control still runs the full pipeline | functional | happy-path control | `test_trust_ordering_attacks.py::test_trusted_same_repo_pr_still_executes_full_pipeline` (plain) |

### Plan W2 — credentials as capabilities (`#5/#6/#13/#15`, D2) — **green**

| Contract | Layer | Coverage | Tests |
|----------|-------|----------|-------|
| Agent env is an explicit allowlist (no `GIT_ASKPASS`, tokens, foreign provider keys) | unit/structural | per-agent parametrization incl. opencode AST scan | `test_credentials.py::test_agent_env_contains_no_credentials`, `test_opencode_agent_env_contains_no_credentials` (plain) |
| Direct `build_agent_env` / strip+active-key maps | unit | planted secrets; opencode keeps none | `test_secrets.py::test_build_agent_env_*`, `test_always_strip_from_agent_env_names`, `test_active_provider_key_by_agent_mapping` (plain) |
| `GIT_ASKPASS` not exported to shared env; file `0o600` in `0o700` dir | unit | permission bits + env scrape | `test_credentials.py` (plain), `test_credential_theft.py::test_shell_cannot_dereference_askpass` (plain) |
| Askpass content/output without requiring `+x` | unit | invoke via `sh <path>` (D2 `0o600`) | `test_git_setup.py::test_askpass_returns_x_access_token_for_username` — **rationale:** W2/D2 mandates non-executable askpass; content/output is asserted via `sh`, not direct exec |
| Temp dir removed on success **and** on raised failure | functional | both paths through real `main()` | `test_credentials.py::test_tmpdir_removed_after_*` (plain) |
| Direct `cleanup_temp_directory` | unit | askpass + tmpdir gone | `test_git_setup.py::test_cleanup_temp_directory_removes_askpass_and_tmpdir` (plain) |
| `wipe_runner_leak_surface` scoped to mergeCraft-owned paths | unit | planted foreign `*.sh` untouched (guard-deletion proof) | `test_credentials.py::test_wipe_leaves_foreign_files_untouched` (plain) |
| Direct `register_created_path` | unit | owned wiped / foreign survives | `test_git_setup.py::test_register_created_path_feeds_scoped_wipe`, `test_credentials.py::test_wipe_still_removes_registered_mergecraft_paths` (plain) |
| Push policy on `delete_branch --remote` / `commit_changes` | functional | disabled + restricted default-branch | `test_shell_push_matrix.py` push-policy cells (plain after W2) |

### Plan W3 — containment (`#4`, D3-containment) — **green**

| Contract | Layer | Coverage | Tests |
|----------|-------|----------|-------|
| Git hooks disabled unless `shell=enabled` | integration | planted malicious `post-checkout` never runs; per-mode split | `test_containment.py`, `test_containment_escapes.py::test_hooks_never_execute_*` (plain) |
| `cwd` escapes rejected | unit + functional | `/etc`, `..`, absolute, symlink; inside-workspace accepted (control) | `test_containment.py`, `test_containment_escapes.py`, `test_workspace.py::test_resolve_allowed_working_directory_*` (plain) |
| No `safe.directory '*'` wildcard | structural + unit | entrypoint text scan + `add_safe_directory` git argv | `test_containment.py::test_entrypoint_safe_directory_has_no_wildcard`, `test_containment_escapes.py`, `test_workspace.py::test_add_safe_directory_*` (plain) |
| Workspace registry | unit | `register_workspace_root`, `ensure_github_workspace_registered`, `WorkspacePathError` | `test_workspace.py` (plain) |
| Agent spawns drop privileges | structural + unit | AST/text pin + `setpriv` argv when uid mocked to 0 | `test_containment.py::test_agent_spawn_drops_privileges`, `test_privilege.py` (`wrap_agent_command`, `wrap_agent_subprocess`, `prepare_workspace_for_agent`, `agent_user_name`) (plain); runtime UID≠0 → W11 |

### Plan W4 — adversarial `shell x push` matrix (`#7`) — **green for W1–W3**

Every cell of `shell ∈ {disabled, restricted, enabled} × push ∈ {disabled,
restricted, enabled}` (9 cells) has ≥1 adversarial test per invariant class.
W5–W12 contracts in `tests/security/` (`test_supply_chain.py`,
`test_process_tree_kill.py`) remain xfail-pending.

| Attack class | Per-cell coverage | Tests |
|--------------|-------------------|-------|
| W4.1 tool-registration deltas | all 9 cells via `CELLS` | `test_shell_push_matrix.py::test_tool_registration_deltas` |
| W4.2 push fail-closed | all 9 cells (`push_branch` + direct `git` subcommands); shell×mode for tags/delete/commit | `test_shell_push_matrix.py` (`test_push_branch_*`, `test_direct_git_push_subcommand_always_blocked`, `test_delete_remote_*`, `test_commit_changes_*`, `test_push_tags_*`) |
| W4.3 credential theft | all 9 cells (`test_matrix_cell_blocks_credential_exfiltration`); restricted×push for env/askpass/token/proc; unit `resolve_env` | `test_credential_theft.py` |
| W4.4 containment escapes | hooks: disabled+restricted × push (6); cwd: restricted × push (3); `safe.directory`: all 9 cells | `test_containment_escapes.py` (+ `test_containment.py` enabled-hooks control) |
| W4.5 trust-ordering attacks | all 9 cells × {fork-PR, `pull_request_target`} | `test_trust_ordering_attacks.py` |

Every guard has a test that fails when the guard is removed — no test asserts a
permissive branch as correct (audit-escape rule). The
`test_shell_enabled_inherits_full_env_by_design` / hooks-under-`enabled`
controls document the documented escape hatch; adversarial cells never treat
those permissive paths as the security bar.

### Plan W5 — RunOutcome taxonomy (`#16`, D3) — **green**

| Contract | Coverage | Tests |
|----------|----------|-------|
| Enum exactly `passed/failed/inconclusive/infra_error/timed_out/configuration_error`, string-valued | unit | `test_run_outcome.py::test_run_outcome_has_exactly_the_d3_values`, `test_run_outcome_is_string_valued` (plain after reconciliation) |
| `RUN_OUTCOME_CONCLUSION` total over D3, only `passed`→`success` | unit, direct symbol | `TestRunOutcomeHelpers::test_run_outcome_conclusion_covers_every_value`, `test_run_outcome_conclusion_only_passed_maps_to_success` (plain) |
| `run_succeeded_for_outcome` true only for `passed` | unit, direct symbol, guard-deletion anchor | `TestRunOutcomeHelpers::test_run_succeeded_for_outcome_true_only_for_passed` (parametrized ×6, plain) — breaks if any non-`passed` outcome were ever treated as succeeded |
| `error_code_for_outcome` stable, namespaced, unique per outcome | unit, direct symbol | `TestRunOutcomeHelpers::test_error_code_for_outcome_is_stable_and_namespaced` (×6), `test_error_code_for_outcome_is_unique_per_outcome` (plain) |
| `passed`/`failed`/`infra_error`/`timed_out` reachable via real `main()` | functional | `test_run_outcome.py::test_passed_outcome_on_successful_run`, `test_failed_outcome_on_agent_failure`, `test_infra_error_outcome_on_agent_exception`, `test_timed_out_outcome_on_timeout` (plain) |
| `configuration_error` reachable via a `cwd` workspace-path escape (no W6 needed) | functional | `test_configuration_error_outcome_on_workspace_path_escape` (plain) |
| `configuration_error` via unparseable `timeout` input; `inconclusive` via prep failure; full 6-outcome conclusion sweep | functional | `test_configuration_error_outcome_on_bad_timeout`, `test_inconclusive_outcome_on_prep_failure`, `test_every_outcome_maps_to_a_check_conclusion` (plain after W6 reconciliation) |
| `_ConfigurationError` classifies as `configuration_error` | unit, direct symbol | `TestConfigurationErrorClassification` (plain, added W6 reconciliation) |
| Failure paths write structured `result` JSON (`outcome` + `error.code`), heredoc multiline | functional | `test_gha_failure_outputs.py::test_failure_writes_structured_result_output` (plain after reconciliation) |
| `_structured_failure_result` payload shape + redaction + code stability | unit, direct symbol | `TestStructuredFailureResult` (plain) |
| `evidence_packet` output parses as `MergeEvidencePacket` | functional | `test_gha_failure_outputs.py::test_evidence_packet_output_parses_as_packet_schema` (plain) |
| `_write_evidence_packet_output` writes packet bytes / tolerates a missing file | unit, direct symbol | `TestWriteEvidencePacketOutput` (plain) |
| Live-path `evidence_packet` output surfacing (packet present / absent) | functional | `tests/evidence/test_run_packet.py::TestActionOutputSurfacing` (retargeted onto `cli/gha_cmd.py` — plain) |
| Dead `action` package's `entry` module gone, unreferenced under `src/` | structural | `test_gha_failure_outputs.py::test_action_entry_module_is_gone` (plain green since 2026-08-11) |

### Plan W6 — fail-closed config (`#12/#30`, D4) — **green**

| Contract | Coverage | Tests |
|----------|----------|-------|
| `extra="forbid"` on security/runtime models with actionable messages | unit ×4 models + `load_repo_settings` integration | `test_extra_forbid.py` (plain after W6 reconciliation; known-keys control plain) |
| Optional-feature warn shim (`_warn_unknown_config_keys`) | unit, direct symbol + model-validator path | `test_extra_forbid.py::test_warn_unknown_config_keys_logs_for_optional_models` (plain, added W6 reconciliation) |
| Prep/dependency failure → `inconclusive` with reason recorded | functional via harness `prep_failure`/`setup_script_rc` | `test_prep_fail_closed.py` (plain after W6; success-path + agent-failure control plain; trusted-tier warn-only plain) |
| Unparseable `timeout` → `configuration_error` at startup; agent never runs | functional | `test_timeout_validation.py::test_unparseable_timeout_fails_closed` (plain after W6); valid-parse + `--notimeout` controls plain |
| Tracing tri-state (unset ≠ false; input > env > YAML > default) | unit + functional | `test_tracing_tri_state.py` (plain after W6 on `_parse_bool(None)`/`enabled=None`/action-wins; CLI-layer controls plain); pre-W6 suite aligned: `tests/tracing/test_config.py::test_tracing_block_parses_and_defaults_unset`, `tests/tracing/exporters/test_action_inputs.py::test_unset_action_inputs_default_to_disabled` (`enabled is None`) |
| Direct `apply_tracing_overrides` precedence | unit, direct symbol | `test_apply_tracing_overrides_input_beats_yaml`, `test_apply_tracing_overrides_env_beats_yaml_when_input_unset`, `test_apply_tracing_overrides_unset_preserves_yaml` (plain, added W6 reconciliation) |
| Per-surface failure policy (hard-fail vs warn-and-disable) | unit × parametrized surfaces | `test_config_failure_policy.py` (enum-invalid plain; unknown-key plain after W6) |

### Plan W7/W8 — supply chain (`#1/#2/#22-#25/#28`)

File-content tests (no image builds): `test_supply_chain.py` —

- W7.1 digest-pinned `FROM` + pinned `uv` in both Dockerfiles (**plain** after W7).
- W7.2 no `curl|wget … | bash` installer pipes (**plain** after W7).
- W7.3 `gh` not from the floating vendor apt repo (**plain** after W7).
- W7.4 `docker/agent-clis/package.json` + `package-lock.json` exist; both Dockerfiles use `npm ci`; no floating `npm install -g` (**plain** after W7).
- W7.5 Dependabot `npm` entry for `/docker/agent-clis` (**plain** after W7).
- W8.1 reusable workflows pinned to 40-char SHAs, no mutable `@v2` (**plain** after W8).
- W8.2 no `secrets: inherit`; ≥2 jobs; per-job `permissions:` (**plain** after W8).
- W8.4 SBOM (syft) + scan (trivy/grype) steps present (**plain** after W8).
- W8.5 cosign + `attest-build-provenance` present (**plain** after W8).

### Plan W9 — runtime robustness (`#14/#34`) — **green**

| Contract | Coverage | Tests |
|----------|----------|-------|
| W9.1 `start_new_session=True` on every agent `Popen` | structural AST ×4 agents | `test_process_tree_kill.py::test_agent_spawns_use_process_groups` (plain) |
| W9.2 timeout kills the process **tree** | functional — real bash CLI double forks a grandchild; grandchild must die; orphan reaped in `finally` | `test_process_tree_kill.py::test_timeout_kills_grandchildren` (plain; POSIX-gated) |
| Direct `process_group` symbols | unit — register/track/kill/wait/kill-all | `test_process_tree_kill.py` (`test_register_process_group_tracks_pid`, `test_kill_process_group_reaps_session_leader`, `test_wait_or_kill_process_group_times_out_and_kills`, `test_track_process_group_registers_for_block_lifetime`, `test_kill_all_active_process_groups_reaps_registered`) |
| W9.3 retryable-vs-permanent classification | unit × status table (429/5xx/transport vs 4xx/unknown) | `test_retry_policy.py::TestTransientClassification` (plain) |
| W9.3 reads bounded-retried, mutations never blind-retried | integration against a counting transport | `TestRetryBehavior` (`test_mutation_5xx_is_not_retried` plain) |
| W9.3 bounded exponential backoff **with jitter** | structural on the retry decorator (no wall-clock asserts) | `TestRetryShape::test_github_client_wait_is_exponential_with_jitter` (plain), `test_github_client_stop_is_bounded` (plain), `test_cursor_cloud_client_has_retry_policy` (plain) |
| Direct `is_retryable_cli_failure` / `retry_transient_safe_methods` | unit — exit/stderr needles + RetryCallState table | `TestRetryableCliFailure`, `TestRetryTransientSafeMethods` (plain) |

### Plan W10 — model evidence + fallback policy (`#20`) — **green**

| Contract | Coverage | Tests |
|----------|----------|-------|
| W10.2 packet records requested/executed model + provider unconditionally | integration via real `emit_run_packet` | `test_model_evidence.py::test_packet_agent_metadata_records_requested_vs_executed_model` (plain) |
| W10.2 fallback index/occurrence fields always present | same packet | `test_packet_agent_metadata_records_fallback_fields` (plain); schema stays closed: `test_agent_metadata_rejects_unknown_keys_still` (plain guard) |
| W10.1 `allow_fallback: false` refuses chain advance, names the policy | unit on `run_with_model_chain` with scripted `run_once` | `test_allow_fallback_false_refuses_chain_advance` (plain — raises `ModelFallbackPolicyError`) |
| W10.3 fallback emits a structured warning | unit + Loguru sink capture | `test_fallback_emits_structured_warning` (plain) |
| Direct `ModelFallbackPolicyError` | unit — subclass + message needles | `test_model_fallback_policy_error_is_runtime_error_naming_policy` (plain) |
| Direct `_attach_model_evidence` | unit — metadata stamp primary + fallback | `test_attach_model_evidence_stamps_metadata_fields`, `test_attach_model_evidence_primary_has_no_fallback_flag` (plain) |
| Direct `_provider_for_model_evidence` | unit — catalog / agent_id / unknown | `test_provider_for_model_evidence_resolves_label` (plain) |

**Pinned interpretation** (impl waves must match or escalate): the W10.2 fields
land on `AgentMetadata` as `requested_model` / `executed_model` / `provider` /
`fallback_index` (int, 0 = primary) / `fallback_occurred` (bool). The W10.1
violation surfaces as `ModelFallbackPolicyError` whose message names "configuration" or
"fallback"; W5 wiring maps it to `configuration_error`.

### Plan W11 — action-image E2E gate (`#3/#36`, D6) — **green**

Pytest-testable pins only (the workflow itself is W11's deliverable):
`test_supply_chain.py::test_e2e_workflow_exists_and_builds_the_image`
(e2e.yml exists, builds the image, `docker run`s it — plain) and
`test_compatibility_matrix_documented` (plain). Direct unit coverage for
`_default_api_base_url` / `GITHUB_API_URL` (D6 mock + GHES) lives in
`tests/utils/test_github.py`.

### Plan W12 — ops contracts (`#21/#26/#27/#29/#31/#33/#35`, D5) — **green**

| Contract | Coverage | Tests |
|----------|----------|-------|
| W12.2/12.4 every declared default parses through its runtime parser | parametrized ×8 inputs + suggest_eval_add | `test_action_yml_contract.py::TestDeclaredDefaultsParse` (plain) |
| W12.2/12.4 documented default == resolved default | `push` prose `Default: restricted`; timeout 1h; status_checks disabled | `TestDocumentedDefaultsMatchRuntime` (plain) |
| Token non-confusion (`INPUT_TOKEN` vs `INPUT_LOGFIRE_TOKEN`) | unit | `test_token_input_is_not_confused_with_logfire_token` (plain) |
| Manifest hygiene: every input wired to env; no hard-coded env values | structural | `TestActionYmlHygiene` (plain) |
| W12.5 `postCheckoutScript` removal (D5) | structural ×3 + settings default | `test_post_checkout_script_removal.py`; `test_settings.py::test_default_settings_match_upstream` (`not hasattr(..., "post_checkout_script")`) |
| W12.4 `_normalize_suggest_eval_add` | unit bool-ish table | `test_payload.py::test_normalize_suggest_eval_add_*` |
| W12.6 structured logs | `resolve_log_format` / `bind_run_context` / `clear_run_context` | `tests/utils/test_log.py` |
| W12.7 `unshare --net` | `network_namespace_available` / `_unshare_argv` | `tests/mcp/test_network_namespace.py` |

D5 executed as **removal** (W12 impl). W\* review gate confirms lock; no keep-path amendment needed unless the gate reverses D5.

## Known non-targets

- The 5 pre-existing darwin-arm64 failures recorded in W0
  (`test_adapter_catches_planted_finding[actionlint|shellcheck|zizmor|hadolint]`,
  one eslint skip) are host-provenance issues, **not** part of this RED suite.
- Live-provider E2E (W11.2 in-image adversarial run, W11.3 nightly matrix) is
  workflow scope; pytest pins the workflow's existence and shape only.

## Verification snapshot

### W1-RED authoring (2026-08-11)

- `uv run pytest --collect-only -q tests` → **1639 collected, 0 errors**
  (1 pre-existing harbor skip).
- RED-suite run (files above) → **110 passed, 115 xfailed, 1 skipped,
  0 failed, 0 XPASS**.
- `make lint` → PASS · `make typecheck` → PASS (mypy strict, 186 source files).

### W1 xfail reconciliation (2026-08-11)

- Removed **5** non-strict `green after W1:` markers; W1 trust-ordering contracts
  are plain green.
- Direct `setup_script_skip_reason` coverage added on untrusted skip + trusted run
  paths (`test_trust_ordering.py`, `test_trust_ordering_attacks.py`).
- Focused pytest on reconciled files must PASS without `--runxfail`.

### W2 xfail reconciliation (2026-08-11)

- Removed **13** non-strict `green after W2:` markers (`test_credentials.py` ×9,
  `test_shell_push_matrix.py` ×4). No W2-tagged xfail deliberately kept.
- Askpass content test: invoke via `sh <path>` so D2 `0o600` (non-executable) holds
  while the username/password output contract is still asserted.
- Direct symbol coverage added: `build_agent_env`, `ALWAYS_STRIP_FROM_AGENT_ENV`,
  `ACTIVE_PROVIDER_KEY_BY_AGENT` (`test_secrets.py`); `cleanup_temp_directory`,
  `register_created_path` (`test_git_setup.py`).
- Focused pytest on reconciled W2 files: **69 passed** (no `--runxfail`).
- `make lint` PASS · `make typecheck` PASS.

### W3 xfail reconciliation (2026-08-11)

- Removed **8** non-strict `green after W3:` markers:
  - `test_containment.py`: `test_hooks_disabled_when_shell_restricted`,
    `test_shell_working_directory_escape_rejected`,
    `test_shell_working_directory_symlink_escape_rejected`,
    `test_entrypoint_safe_directory_has_no_wildcard`,
    `test_agent_spawn_drops_privileges`
  - `test_containment_escapes.py`: `test_hooks_never_execute_unless_shell_enabled`,
    `test_working_directory_escapes_rejected`,
    `test_safe_directory_wildcard_absent`
- Deliberately kept: none of the production-readiness containment markers.
  Runtime agent UID≠0 remains deferred to W11 in-image (structural `setpriv`
  coverage only on host). Unrelated `tests/agents/*` `green after W3:` markers
  (custom multi-provider gateways — different program) left untouched.
- Direct symbol coverage added:
  - `tests/utils/test_workspace.py`: `WorkspacePathError`, `add_safe_directory`,
    `register_workspace_root`, `ensure_github_workspace_registered`,
    `resolve_allowed_working_directory`
  - `tests/utils/test_privilege.py`: `agent_user_name`, `wrap_agent_command`,
    `wrap_agent_subprocess`, `prepare_workspace_for_agent`
- Focused pytest (containment + new utils): **45 passed** (no `--runxfail`).
- `make lint` PASS · `make typecheck` PASS.

### W4 adversarial proof / matrix verify (2026-08-11)

- **No W1–W3 xfail markers remained** to remove; bounce escalations: **none**.
- Gap fills (plain green against W3 tree):
  - `test_credential_theft.py`: askpass/token/proc parametrized over all
    `push` modes; new `test_matrix_cell_blocks_credential_exfiltration` covers
    all 9 `shell x push` cells (restricted scrape + non-restricted no-shell-tool
    + agent-env allowlist).
  - `test_trust_ordering_attacks.py`: full `shell x push` matrix on untrusted
    setup-script skip + trust-precedes-`setup_git`.
  - `test_shell_push_matrix.py`: `test_direct_git_push_subcommand_always_blocked`
    expanded to all 9 cells.
  - `test_containment_escapes.py`: `test_safe_directory_wildcard_absent`
    expanded to all 9 cells.
- Focused `uv run pytest tests/security/ -q` (no `--runxfail`):
  **158 passed, 3 skipped** (`/proc` Linux-only ×3 push modes), **22 xfailed**
  (W7/W8/W9/W11 supply-chain + process-tree only), **0 failed, 0 XPASS**.
- W1–W3 invariant files alone (excl. supply_chain + process_tree_kill): all
  plain green.
- `make test` path: suite lives under `tests/security/` — picked up by
  `make test` (`pytest tests -m "not integration"`); no new Make target.
- `make lint` PASS · `make typecheck` PASS (mypy strict).
- W5–W12 contracts remain xfail-pending per the schedule table above.

### W5 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **9** non-strict `green after W5:` markers:
  - `test_run_outcome.py`: lifted the module-level `pytestmark` (was applied
    to all 9 tests); `test_run_outcome_has_exactly_the_d3_values`,
    `test_run_outcome_is_string_valued`, `test_passed_outcome_on_successful_run`,
    `test_failed_outcome_on_agent_failure`, `test_infra_error_outcome_on_agent_exception`,
    `test_timed_out_outcome_on_timeout` are now plain green (6 markers).
  - `test_gha_failure_outputs.py`: `test_failure_writes_structured_result_output`
    (plain — W5.3 landed) and `test_evidence_packet_output_parses_as_packet_schema`
    (plain — W5.4 landed; fixture bug fixed first, see below) (2 markers).
  - `tests/evidence/test_run_packet.py::TestActionOutputSurfacing`: the two
    live, non-xfail tests that imported the doomed `action` package's `entry`
    module directly were **retargeted**, not merely un-xfailed — they were
    never marked xfail (a pre-existing test-authoring gap), so this bullet
    counts the retarget, not a marker removal (1 file, 2 tests, 0 markers to
    remove — see "Entry-module retarget" below).
- Deliberately **kept** (3, all still needing W6 product code — dual-tagged
  in the RED tests' own docstrings since W1-RED):
  - `test_configuration_error_outcome_on_bad_timeout` (W6.3 — an unparseable
    `timeout` input does not yet fail closed; it warns and falls back to 1h,
    so the run still completes as `passed`).
  - `test_inconclusive_outcome_on_prep_failure` (W6.1 — prep/dependency
    failure does not yet map to `inconclusive`; `start_installation` failure
    is currently silent to the outcome).
  - `test_every_outcome_maps_to_a_check_conclusion` (needs both of the above
    fixed — it drives all six outcomes end-to-end in one sweep).
  - (`test_action_entry_module_is_gone` was kept at the time of this original
    W5 reconciliation pass, pending the W5.5 deletion — see the 2026-08-11
    "tiny reconciliation, post-deletion" log entry above: the executor's
    W5.5 wave has since deleted `src/mergecraft/action/entry.py` and the
    marker has been removed; the test is plain green.)
- **Entry-module retarget (unblocks W5.5):** `tests/evidence/test_run_packet.py`
  `TestActionOutputSurfacing::test_packet_path_is_written_to_github_output` and
  `::test_absent_packet_omits_the_output` imported the dead `action` package's
  `entry` module (`_write_outputs`) directly and were live, non-xfail tests —
  the actual blocker the W5 wave-plan notes named. Retargeted onto the real
  entrypoint (`action.yml` -> `docker-entrypoint.sh` -> `mergecraft gha` ->
  `cli/gha_cmd.py::_run_main`): the "packet present" case now calls
  `_write_evidence_packet_output` directly (asserting the packet JSON body,
  not the old writer's bare-path value — W5.4's pinned interpretation); the
  "packet absent" case now drives `_run_main` end-to-end and asserts the
  output key is never set, since that call-site decision (skip the writer
  when `evidence_packet_path` is falsy) lives in `_run_main`, not the writer.
  `rg -n 'action\.entry|action/entry' tests/` → **0 hits** (whole-repo sweep
  also 0 outside the doomed module itself) — **ready for the W5.5 deletion
  pass**. `test_action_entry_module_is_gone` itself deliberately builds the
  dotted/slashed path from parts (`_pkg, _mod = "action", "entry"`) so it does
  not show up as a false positive in that same sweep.
- **Fixture bug fixed:** `test_evidence_packet_output_parses_as_packet_schema`
  constructed `MergeEvidencePacket(...)` without the required
  `schema_version=PACKET_SCHEMA_VERSION` kwarg (D7 pinned field), raising
  `pydantic.ValidationError` before the W5.4 wiring under test ever ran —
  unrelated to the implementation, a pre-existing authoring bug flagged by the
  W5 impl wave. One-line fix; test now exercises the real wiring and passes.
- **New direct-symbol tests** (previously-unbacked deliverables, zero
  `tests/` references before this pass):
  - `TestRunOutcomeHelpers` (`test_run_outcome.py`): `RUN_OUTCOME_CONCLUSION`
    (totality + only-`passed`-is-`success`), `run_succeeded_for_outcome`
    (parametrized ×6, guard-deletion anchor — fails if any non-`passed`
    outcome were ever treated as succeeded), `error_code_for_outcome`
    (stability + uniqueness, parametrized ×6).
  - `TestStructuredFailureResult` (`test_gha_failure_outputs.py`): payload
    shape, secret redaction, and `error.code` == `error_code_for_outcome`
    agreement (parametrized ×6).
  - `TestWriteEvidencePacketOutput` (`test_gha_failure_outputs.py`): writes
    packet bytes as the output value; a missing/unreadable packet file logs
    and skips rather than raising.
  - New scenario `test_configuration_error_outcome_on_workspace_path_escape`
    (`test_run_outcome.py`): a `cwd` (`INPUT_CWD`) outside the allowed
    workspace roots raises `WorkspacePathError` (W3), which
    `_classify_error_outcome` (W5.2) maps to `configuration_error` — reachable
    today without any W6 machinery, unlike the bad-`timeout` trigger. No
    status-check assertion: the escape is rejected before `ToolContext`
    exists, and `main()`'s outer handler only reports a status check
    `if tool_context:` — confirmed via `rec.report_status_calls == []`.
- Focused pytest, reconciled files (`test_run_outcome.py`,
  `test_gha_failure_outputs.py`, `test_run_packet.py`), no `--runxfail`:
  **55 passed, 4 xfailed** (the 4 kept above), **0 failed, 0 XPASS**.
  With `--runxfail` the same 4 genuinely fail (not accidental XPASS) —
  confirms they are still correctly blocked, not stale markers.
- `uv run pytest --collect-only -q tests` → **1748 collected, 0 errors**
  (1 pre-existing harbor skip).
- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests -m "not integration" -q` →
  **1605 passed, 5 failed, 25 skipped, 3 deselected, 66 xfailed, 45 xpassed**.
  The 5 failures are the same pre-existing darwin-arm64 host-provenance
  failures recorded at W0 (unrelated to this reconciliation, no new
  failures). No unexpected XPASS among the W5 files.
- `make lint` PASS · `make typecheck` PASS (mypy strict, 189 source files).
- No commits, no push (C2) — see the wave-plan checklist annotation.

### W6 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **16** non-strict `green after W6:` decorators covering **20** previously
  XPASSing cases:
  - `test_extra_forbid.py` ×4 (`test_unknown_key_is_rejected` parametrized ×4 models,
    `test_unknown_key_error_names_the_key`, `test_unknown_key_error_is_actionable`,
    `test_load_repo_settings_fails_closed_on_unknown_key`)
  - `test_tracing_tri_state.py` ×5 (`test_parse_bool_unset_is_none_not_false`,
    `test_action_inputs_unset_tracing_resolves_to_none`,
    `test_tracing_settings_enabled_defaults_to_unset`,
    `test_action_input_wins_over_yaml_on_live_path`,
    `test_action_input_true_enables_tracing_on_live_path`)
  - `test_timeout_validation.py` ×1 (`test_unparseable_timeout_fails_closed_before_agent_runs`)
  - `test_prep_fail_closed.py` ×2 (`test_prep_failure_makes_run_inconclusive`,
    `test_prep_failure_reason_is_recorded`)
  - `test_config_failure_policy.py` ×1 (`test_security_surface_unknown_keys_fail_closed`
    parametrized ×2)
  - `test_run_outcome.py` ×3 (`test_configuration_error_outcome_on_bad_timeout`,
    `test_inconclusive_outcome_on_prep_failure`,
    `test_every_outcome_maps_to_a_check_conclusion`)
- Deliberately **kept**: none of the production-readiness W6 markers. Unrelated
  `tests/utils/test_learnings_provenance.py` `green after W6:` markers (security-
  learnings-provenance program) left untouched.
- **New direct-symbol tests** (previously zero `tests/` name refs):
  - `apply_tracing_overrides` — `test_tracing_tri_state.py::test_apply_tracing_overrides_*`
    (input beats YAML; env beats YAML when input unset; unset preserves YAML)
  - `_ConfigurationError` — `test_run_outcome.py::TestConfigurationErrorClassification`
    (classifies via `_classify_error_outcome`; is a `RuntimeError`)
  - `_warn_unknown_config_keys` — `test_extra_forbid.py::test_warn_unknown_config_keys_logs_for_optional_models`
    (direct call + `ModeDefinition` validator path; names key + model)
- Focused pytest (reconciled W6 files), no `--runxfail`: **75 passed**, **0 failed**,
  **0 xfailed**, **0 XPASS**.
- `make lint` PASS · `make typecheck` PASS (mypy strict, 188 source files).
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W6 xfail reconciliation)`.

### W7 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **6** non-strict `green after W7:` decorators covering **10** cases
  (parametrized ×2 Dockerfiles where applicable) in
  `tests/security/test_supply_chain.py`:
  - `test_base_images_pinned_by_digest` (W7.1)
  - `test_uv_installer_pinned` (W7.1)
  - `test_no_curl_pipe_bash` (W7.2)
  - `test_gh_install_is_pinned` (W7.3)
  - `test_agent_clis_come_from_lockfile` (W7.4)
  - `test_dependabot_covers_agent_clis` (W7.5)
- Deliberately **kept** (same file; need W8/W11 product changes):
  - W8: `test_reusable_workflows_sha_pinned` (×2 workflows),
    `test_release_pipeline_least_privilege`,
    `test_release_pipeline_produces_sbom_and_scan`,
    `test_release_pipeline_signs_and_attests` (4 markers / 5 cases)
  - W11: `test_e2e_workflow_exists_and_builds_the_image`,
    `test_compatibility_matrix_documented` (2 markers)
  - No dual-tagged W7/W8 tests existed; nothing ambiguous to leave half-lifted.
- Focused pytest `tests/security/test_supply_chain.py`, no `--runxfail`:
  **10 passed**, **7 xfailed** (W8+W11), **0 failed**, **0 XPASS**.
- `make lint` PASS.
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W7 xfail reconciliation)`.

### W8 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **4** non-strict `green after W8:` decorators covering **5** cases
  in `tests/security/test_supply_chain.py`:
  - `test_reusable_workflows_sha_pinned` (W8.1; parametrized ×2 workflows)
  - `test_release_pipeline_least_privilege` (W8.2)
  - `test_release_pipeline_produces_sbom_and_scan` (W8.4)
  - `test_release_pipeline_signs_and_attests` (W8.5)
- Deliberately **kept** (same file; need W11 product changes):
  - W11: `test_e2e_workflow_exists_and_builds_the_image`,
    `test_compatibility_matrix_documented` (2 markers)
  - Unrelated `tests/status_checks/conftest.py` docstring mentioning a
    different program's "green after W8" left alone.
- Focused pytest `tests/security/test_supply_chain.py`, no `--runxfail`:
  **15 passed**, **2 xfailed** (W11 only), **0 failed**, **0 XPASS**.
- `make lint` PASS.
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W8 xfail reconciliation)`.

### W9 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **5** non-strict `green after W9:` markers:
  - `test_process_tree_kill.py`: `test_agent_spawns_use_process_groups`,
    `test_timeout_kills_grandchildren`
  - `test_retry_policy.py`: `test_mutation_5xx_is_not_retried`,
    `test_github_client_wait_is_exponential_with_jitter`,
    `test_cursor_cloud_client_has_retry_policy`
- Deliberately **kept:**
  - `tests/evidence/test_gate_actions.py` module-level
    `green after W9/W10` — belongs to the **merge-evidence** wave plan
    (WD-T gate-action map), not production-readiness W9 process-group/retry
    contracts; left untouched.
- Direct symbol coverage added (previously zero `tests/` refs):
  - `kill_process_group`, `wait_or_kill_process_group`, `track_process_group`,
    `kill_all_active_process_groups`, `register_process_group`
    (`test_process_tree_kill.py`)
  - `is_retryable_cli_failure`, `retry_transient_safe_methods`
    (`test_retry_policy.py::TestRetryableCliFailure`,
    `TestRetryTransientSafeMethods`)
- Focused pytest
  `tests/security/test_process_tree_kill.py tests/utils/test_retry_policy.py`,
  no `--runxfail`: **41 passed**, **0 failed**, **0 xfailed**, **0 XPASS**.
- `make lint` PASS · `make typecheck` PASS.
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W9 xfail reconciliation)`.

### W10 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **4** non-strict `green after W10:` markers from
  `tests/evidence/test_model_evidence.py` (module `_W10_XFAIL` + four uses):
  - `test_packet_agent_metadata_records_requested_vs_executed_model`
  - `test_packet_agent_metadata_records_fallback_fields`
  - `test_allow_fallback_false_refuses_chain_advance` (now asserts
    `ModelFallbackPolicyError` by type)
  - `test_fallback_emits_structured_warning`
- Deliberately **kept:**
  - `tests/evidence/test_gate_actions.py` module-level `green after W9/W10` —
    belongs to the **merge-evidence** wave plan (WD-T gate-action map), not
    production-readiness W10 model-evidence/fallback contracts; left untouched.
- Direct symbol coverage added (previously zero `tests/` refs):
  - `ModelFallbackPolicyError`
  - `_attach_model_evidence` (primary + fallback stamp)
  - `_provider_for_model_evidence` (catalog / agent_id / unknown)
- Focused pytest `tests/evidence/test_model_evidence.py`, no `--runxfail`:
  **12 passed**, **0 failed**, **0 xfailed**, **0 XPASS**.
- `make lint` PASS · `make typecheck` PASS.
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W10 xfail reconciliation)`.

### W11 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **2** non-strict `green after W11:` markers from
  `tests/security/test_supply_chain.py`:
  - `test_e2e_workflow_exists_and_builds_the_image` (W11.1)
  - `test_compatibility_matrix_documented` (W11.3)
- Deliberately **kept:**
  - W12 markers in `tests/action/test_action_yml_contract.py` /
    `tests/config/test_post_checkout_script_removal.py` (`green after W12:`)
  - Unrelated merge-evidence `test_gate_actions.py` W9/W10 markers
- Direct symbol coverage added (previously zero `tests/` refs):
  - `_default_api_base_url` — default / `GITHUB_API_URL` honour / trailing-slash
    strip + `GitHubClient` wiring when `base_url` omitted
    (`tests/utils/test_github.py`)
- Focused pytest `tests/security/test_supply_chain.py
  tests/utils/test_github.py`, no `--runxfail`:
  **24 passed**, **0 failed**, **0 xfailed**, **0 XPASS**.
- `make lint` PASS.
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W11 xfail reconciliation)`.

### W12 xfail reconciliation (2026-08-11, per-impl-wave)

- Removed **4** W12 xfail sites:
  - `test_action_yml_contract.py::test_push_default_prose_matches_resolution`
    (`@pytest.mark.xfail`)
  - `test_post_checkout_script_removal.py` ×3 (`_W12_XFAIL`)
  - Deleted the runtime `pytest.xfail(...)` branch in
    `test_suggest_eval_add_default_parses` (now asserts plain success)
- Amended non-xfail leftover: `tests/config/test_settings.py` no longer reads
  `settings.post_checkout_script` — asserts `not hasattr(..., "post_checkout_script")`
  (D5 removal). `rg` hits under `tests/` are docs/assertions that the field is
  **gone**, not plumbing.
- Deliberately **kept:** none for production-readiness W12. Unrelated other-
  program xfails (`test_gate_actions.py` W9/W10, learnings-provenance, etc.)
  untouched.
- Direct symbol coverage added (previously zero `tests/` refs):
  - `resolve_log_format`, `bind_run_context`, `clear_run_context`
    (`tests/utils/test_log.py`)
  - `network_namespace_available`, `_unshare_argv`
    (`tests/mcp/test_network_namespace.py`)
  - `_normalize_suggest_eval_add` (`tests/utils/test_payload.py`)
- Focused pytest (action contract + postCheckout removal + settings + log +
  netns + normalize), no `--runxfail`: **57 passed**, **0 failed**,
  **0 xfailed**, **0 XPASS**.
- `make lint` PASS · `make typecheck` PASS.
- No commits, no push (C2) — `(2026-08-11 ✅: no-commit-per-C2 — W12 xfail reconciliation)`.
- **Ready for W\* review gate.**