# Thermos pins — 20d lane A engine (behavioral)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md`.
Grep-style pins (`engine.run(`, `timeout=engine.timeout_s(...)`, `inspect.getsource`,
AST walks) were replaced with behavioral tests. Some CLI/Action/SCM/cache contracts
stay RED until impl lands. No pin that `offline_review.py` stays under 1000 lines
(parent may extract). D17/D13/D16: this suite does not touch lane B files and does
not add write-capability tests that enable Fix.

| Contract | Tests | Expected until impl |
|---|---|---|
| Cache key == agent run identifier (`resolve_model` None is hashed; config slug is not) | `tests/offline_review/test_result_cache.py::test_cache_key_hashes_none_when_resolve_model_returns_none` | RED if cache still falls back to `resolve_effective_model_slug` |
| Resolved slug hashed **and** passed to `_run_agent_review` | `test_cache_key_and_agent_share_resolved_model_slug` | RED if agent still receives CLI `model=None` while cache hashes the slug |
| Empty vs resolved model hashes differ | `tests/utils/test_review_result_cache.py::test_review_result_cache_key_empty_model_differs_from_resolved_slug` | keep |
| Finalize before store; cache-hit re-finalize | `tests/offline_review/test_result_cache.py` | keep |
| SCM identity map; `stages_ran == ()`; no fake `run_sync` | `tests/review/test_review_engine_behavior.py::test_scm_conforming_request_runs_engine_and_exposes_stage_specs` | RED while `conforming_review_request` no-op-runs the engine |
| CLI/Action/SCM actually produce `ReviewSnapshot` (`isinstance`) | `tests/review/test_da_review_snapshot.py` | keep (behavioral, not getsource) |
| CLI analyze calls `run_analyzer_pipeline` when enabled | `tests/offline_review/test_analyze_stage.py` | RED while `_analyze` only reads `settings.analyzers.enabled` |
| Disabled analyzers skip the pipeline | same | may already be GREEN |
| Canonical review timeout is 1h **data**; `engine_enforced is False` | `test_canonical_snapshot_records_review_timeout_as_data_not_engine_enforced` | RED until `ReviewStageSpec.engine_enforced` exists |
| No overlay: 1ms snapshot does not `wait_for`-cancel self-timed review | `test_engine_does_not_wait_for_self_timed_review_without_timeouts_overlay` | RED until engine honors `engine_enforced=False` |
| Numeric `timeouts={"review": 0.02}` still enforces | `test_engine_run_timeout_omits_incomplete_stage_from_stages_ran` | keep |
| Action `main` does not pass `timeouts["review"]=None` | `test_action_main_calls_engine_run` | RED while `main` passes that overlay |
| `engine.timeout_s("review") == 3600.0` | constructor test | keep |
| Delete `run_from_snapshot` factory | `test_review_package_reexports_engine_types` | RED until the re-export is gone |
| Skip-agent: `_publish` not from review hook; `_finalize` owns publish | `test_skip_agent_publish_is_owned_by_finalize` | RED while skip-agent calls `_publish` then `_ShortCircuit` |
| Protocol: `run_started` without phase theater | `tests/cli/test_protocol_wired_into_agent.py` | RED while `_start_agent_protocol` emits materialize/review phases |
| Direct `negotiate_protocol` / `VERSION_FIELD_ALIASES` / `PROTOCOL_BUDGET_FIELDS` | `tests/cli/test_da_protocol_negotiation.py` | keep |
| `_run_offline_diff_review` has no `resume` param | `tests/cli/test_resume_result_cache.py::test_run_offline_diff_review_body_has_no_distinct_resume_parameter` | RED while the private signature still has `resume` |
| CLI `--resume` help text | same file | keep |
| Exactly one `ReviewEngine` on CLI dry-run | `test_cli_review_constructs_exactly_one_engine` | RED if CLI and offline each construct |
| Dry-run executes materialize→analyze→review→publish | `test_cli_review_drives_engine_run` | keep (behavioral wrap of `engine.run`) |
| JSONL reuse via calling `load_trace_jsonl_events` | `tests/cli/test_trace_jsonl_reuse.py` | keep |
| Streaming boundary via import/call, not AST | `tests/cli/test_finding_stream_boundary.py` | keep |
| Thin path: no per-agent fork; no `run_from_snapshot` source pin | `tests/cli/test_thin_agent_review_path.py` | keep |
| CLI `TimeoutError` calls `cleanup_review_subprocesses` | `test_cli_review_timeout_cleans_up_subprocesses` | keep |
| Action publish `TimeoutError` → `RunOutcome.timed_out` | `test_action_publish_timeout_is_timed_out_outcome` | keep |
| `AGENT_PROTOCOL_VERSION` aliases snapshot protocol | `test_protocol_and_schema_versions_alias_the_snapshot` | keep |

Deleted as a feature pin: `test_engine_timeouts_none_disables_wait_for_for_that_stage`.

Existing DA files that must stay green: `tests/review/test_da_review_snapshot.py` (except new isinstance pins that follow the same objects), `tests/cli/test_da_first_finding_stream.py`, `tests/cli/test_da_protocol_negotiation.py`, `tests/cli/test_thin_agent_review_path.py`, `tests/cli/test_da_missing_verbs.py`.
