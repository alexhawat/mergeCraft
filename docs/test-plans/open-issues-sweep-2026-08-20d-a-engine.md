# Open issues sweep 2026-08-20d-a-engine — Batch DA + DD test plan (#377–#380, #383)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md`
Worktree: `.ignorelocal/worktrees/open-issues-sweep-2026-08-20d-a-engine` @ `wave/20d-a-engine`
Authoring wave: **W2** (DA RED) · Implementation: **W3–W6** · W3 xfail markers removed after remaining #377 verbs landed · W4 xfail markers removed after first-finding stream / cache / resume / goldens landed · W5 xfail markers removed after protocol negotiation / D12 adapter landed · W6 xfail markers removed after ReviewSnapshot conformance landed.

**W9 / #383** tests authored 2026-08-21 (Batch DD RED). W9.1 xfails removed
after `docs/agent-loop.md` landed. Do **not** name a module `adversarial.py`
(D17 — lane B owns `src/mergecraft/evals/adversarial.py`). D16: nothing under
`skills/`. D13 write/Fix pins live here, not in the DA suite.

## xfail schedule

All cross-wave markers use `@pytest.mark.xfail(..., strict=False)`.

| Wave | Tests | Marker reason | Status |
|------|-------|---------------|--------|
| **W3** | remaining #377 verbs (not `describe` / `capabilities`) | markers removed after W3 | GREEN |
| **W4** | first-finding stream, resume, result cache, cancel cleanup, goldens | markers removed after W4 | GREEN |
| **W5** | negotiate / retryable mismatch / budgets / D12 adapter | markers removed after W5 | GREEN |
| **W6** | `ReviewSnapshot` type + CLI / Action / SCM conformance | markers removed after W6 | GREEN |
| **W9** | `docs/agent-loop.md` + append-only manifest row | markers removed after W9.1 | GREEN |
| **W9** | agent-mode D13 boundary + thin integrations | no xfail (product already refuses) | GREEN guards |

Green guards (no xfail): D8 inherit `describe` / `capabilities`; unknown verb →
usage exit 2; dual `schema_version` vs `protocol_version` stamps (aliased, both
survive); hidden `diff-review` alias. DA379d
`test_agent_protocol_module_has_no_negotiate_export` **deleted** after
`negotiate_protocol` landed (current-state negative). DAF recon: deleted
`tests/config/test_ce_schema.py::test_agent_protocol_does_not_negotiate_capabilities`
(#368 source-scan that forbade `negotiate` in `agent_protocol.py`); canonical
pins remain in `tests/cli/test_da_protocol_negotiation.py`.

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| DA377a | `describe` / `capabilities` stay registered (D8) | functional | happy | `tests/cli/test_da_missing_verbs.py::test_inherited_20c_verbs_remain_registered` |
| DA377b | Unknown root verb is usage-exit 2 | functional | error | `test_unknown_root_verb_is_still_usage_exit` |
| DA377c | `explain` / `ask` / `replay` registered + `--help` | functional | happy | `test_remaining_root_verb_is_registered`, `test_root_help_lists_remaining_verb` |
| DA377d | `run inspect` / `run diff` (root `run` typer, not `analyzers run`) | functional | happy + edge | `test_run_typer_exposes_inspect_and_diff`, `test_remaining_verbs_are_not_the_config_or_analyzers_homonyms` |
| DA377e | JSON payloads carry `schema_version` (D11) | functional | happy | `test_remaining_verb_json_payload_carries_schema_version`, `test_run_subcommand_json_payload_carries_schema_version` |
| DA377f | New modules use consoles + named exits + schema_version (D11) | unit | happy | `test_remaining_verb_module_uses_d11_surface` |
| DA378a | First finding emits while review is still running | functional | happy | `tests/cli/test_da_first_finding_stream.py::test_first_finding_emits_while_review_is_still_running` |
| DA378b | `review --resume` documented | functional | happy | `test_review_help_documents_resume` |
| DA378c | Review result cache beyond `mergecraft cache` | functional | happy | `test_review_help_documents_result_cache_beyond_cache_typer` |
| DA378d | Cancellation cleans up subprocesses | unit | error | `test_diff_review_cmd_exposes_cancellation_subprocess_cleanup` |
| DA378e | Reusable CLI golden at `tests/cli/goldens/review_first_finding.jsonl` (RV5) | functional | happy | `test_reusable_cli_golden_for_first_finding_exists` |
| DA379a | CLI JSON stamps `schema_version` `1.0.0` | unit | happy (current) | `tests/cli/test_da_protocol_negotiation.py::test_cli_json_stamps_schema_version` |
| DA379b | Agent JSONL stamps flat `protocol_version` `1` | unit | happy (current) | `test_agent_jsonl_stamps_flat_protocol_version` |
| DA379c | Dual fields remain distinct (D12 aliased, both survive) | unit | edge (current) | `test_schema_version_and_protocol_version_are_distinct_unreconciled_fields` |
| DA379d | No negotiate export (deleted after W5) | unit | current gap | **deleted** — `test_agent_protocol_module_has_no_negotiate_export` |
| DA379e | `negotiate_protocol` selects a version | unit | happy | `test_negotiate_protocol_selects_a_mutually_supported_version` **GREEN** |
| DA379f | Mismatch is retryable | unit | error | `test_protocol_mismatch_is_retryable` **GREEN** |
| DA379g | Named `PROTOCOL_BUDGET_FIELDS` (not ad-hoc kwargs) | unit | edge | `test_protocol_declares_budget_fields_for_negotiation` **GREEN** |
| DA379h | D12 adapter mentions both field names (no survivor guess) | unit | happy | `test_d12_exposes_a_version_field_adapter_without_picking_the_survivor` **GREEN** |
| DA380a | `review` listed; `diff-review` hidden | functional | happy (current) | `tests/review/test_da_review_snapshot.py::test_review_is_the_documented_command` |
| DA380b | Hidden `diff-review` remains invocable | functional | edge (current) | `test_hidden_diff_review_alias_remains_invocable` |
| DA380c | `ReviewSnapshot` type exists | unit | happy | `test_review_snapshot_type_exists` |
| DA380d | One engine callable accepts `ReviewSnapshot` | unit | happy | `test_shared_engine_accepts_review_snapshot` |
| DA380e | CLI review builds a snapshot | integration | happy | `test_cli_review_path_builds_a_review_snapshot` |
| DA380f | Action/`mergecraft.main` builds a snapshot | integration | happy | `test_action_path_builds_a_review_snapshot` |
| DA380g | SCM `conforming_review_request` feeds a snapshot | integration | happy | `test_scm_conforming_request_builds_or_feeds_a_review_snapshot` |

Existing greens **not duplicated:** `tests/cli/test_agent_protocol.py` (flat
`protocol_version` on `--agent` events).

Golden entry point for file 8 RV5: `tests/cli/goldens/review_first_finding.jsonl`
(now exists — JSONL agent events via `format_event_line`, finding before verdict,
no `stdout_stream`/`stderr_stream` keys). D11: JSONL CLI/agent output only; no
second stdout/stderr split.

---

## Batch DD — W9 / #383 (agent loop + capability boundary)

Do not duplicate `tests/cli/test_capabilities_cmd.py` or
`tests/modes/test_review_only_boundary.py`. Do not create `skills/**`. Do not
edit `src/mergecraft/evals/**`, `SECURITY.md`, or `src/mergecraft/cli/app.py`.
Packaging Codex/Gemini/OpenCode is out of scope (file 8 RV3). Protocol
negotiation is #379 (already shipped).

### Impl must satisfy (W9.1 — GREEN; markers removed)

`docs/agent-loop.md` must exist (not under `skills/`, not AGENTS.md / README.md).
Body must:

- Describe the five-step loop: external agent **changes** code → mergeCraft
  **reviews** → agent **consumes findings** → agent **decides** what to change →
  mergeCraft reviews the new **diff**.
- Name `mergecraft review --agent` and JSONL events `run_started`, `phase`,
  `finding`, `verdict`, `run_finished`.
- Point at `docs/EXIT-CODES.md` (or EXIT-CODES) and mention named exits
  `0` / `10` / `11` / `12` / `20` / `30` / `40` / `50` / `2`.
- Cite both `protocol_version` and `schema_version` (D12 adapter; both survive).

`docs/manifest.yaml` must contain **an** append-only row (need not be last —
lane B also appends) with `path: docs/agent-loop.md` and non-empty
`audience`, `template`, and `purpose`. Existing rows must not be rewritten.

### Contract matrix

| # | Contract | Layer | Scenario | Primary test | Marker |
|---|----------|-------|----------|--------------|--------|
| DD383a | `docs/agent-loop.md` exists under `docs/` | functional | happy | `tests/docs/test_agent_loop.py::test_agent_loop_page_exists_under_docs` | GREEN |
| DD383b | Not skills/ / AGENTS.md / README.md (D16/D6) | functional | edge | `test_agent_loop_is_not_a_skill_or_landing_page` | GREEN |
| DD383c | Five-step loop (change → review → consume findings → decide → review new diff) | functional | happy | `test_agent_loop_describes_the_five_step_loop` | GREEN |
| DD383d | Names `mergecraft review --agent` + five JSONL events | functional | happy | `test_agent_loop_names_review_agent_and_jsonl_events` | GREEN |
| DD383e | Cites EXIT-CODES and named exits 0/10/11/12/20/30/40/50/2 | functional | happy | `test_agent_loop_points_at_exit_codes` | GREEN |
| DD383f | Manifest row `path: docs/agent-loop.md` + audience/template/purpose | functional | happy | `test_manifest_includes_agent_loop_row` | GREEN |
| DD383g | Page cites `protocol_version` and `schema_version` (D12) | functional | edge | `test_agent_loop_cites_d12_version_fields` | GREEN |
| DD383h | Agent JSONL has no write events | unit | happy | `tests/agents/test_capability_boundary.py::test_agent_protocol_stream_methods_are_read_only_events` | GREEN |
| DD383i | `format_event_line` / source literals exclude write event names | unit | edge | `test_format_event_line_does_not_define_write_events`, `test_agent_protocol_source_has_no_write_event_literals` | GREEN |
| DD383j | `review --agent` only emits documented event names | functional | happy | `test_review_agent_stream_only_emits_documented_events` | GREEN |
| DD383k | `AgentProtocolStream` helpers are not a write backdoor | unit | error | `test_agent_protocol_stream_emit_rejects_undocumented_write_names` | GREEN |
| DD383l | `/mcp/reviewer` classes omit repo-mutation / shell | unit | happy | `test_primary_reviewer_classes_exclude_repository_mutation` | GREEN |
| DD383m | `build_reviewer_tools` omits `commit_changes` / `push_branch` | integration | happy | `test_reviewer_toolset_does_not_admit_commit_or_push` | GREEN |
| DD383n | Coding agent (`codex`/`gemini`/`opencode`/`cursor`) cannot shell-edit tracked file | functional | error | `test_coding_agent_cannot_edit_tracked_file_via_shell` | GREEN |
| DD383o | Same agents cannot `commit_changes` | functional | error | `test_coding_agent_cannot_commit_changes` | GREEN |
| DD383p | Same agents cannot `push_branch` | functional | error | `test_coding_agent_cannot_push_branch` | GREEN |
| DD383q | `agent_protocol.py` + `--agent` path never invoke git commit/push | unit | error | `test_agent_protocol_and_review_agent_path_do_not_invoke_git_writes` | GREEN |
| DD383r | Agent-mode honors `FORBIDDEN_CAPABILITIES` registry (thin import) | unit | happy | `test_agent_mode_must_honor_forbidden_capability_registry` | GREEN |
| DD383s | `diff_review_cmd` uses one `run_from_snapshot` / `run_offline_diff_review` | unit | happy | `tests/cli/test_thin_agent_review_path.py::test_review_entry_is_not_forked_per_agent_binary` | GREEN |
| DD383t | No `if agent == "codex":` review-behaviour fork in CLI agent/review path | unit | edge | `test_cli_agent_review_path_has_no_per_agent_behaviour_fork` | GREEN |
| DD383u | `run_from_snapshot` is agent-agnostic | unit | happy | `test_shared_engine_callable_is_agent_agnostic` | GREEN |

Already-true D13 product refusals (MCP review-only, no write JSONL events, thin
single review path) ship as **green guards**. W9.1 loop page + manifest row
markers removed after impl (`b821e477`).
