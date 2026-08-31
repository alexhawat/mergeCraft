# Agent isolation (lane E) — test plan (W1 RED)

Wave plan: `.ignorelocal/waves/18-agent-isolation-wave-plan.md`
Worktree: `../mergecraft-agent-isolation` on `wave/agent-isolation`
Authoring wave: **W1** (`test-creator`). Implementation: **W2** (broker), **W3** (Codex wire-up).
xfail-reconciliation: per impl wave (`strict=False` until green; test-creator agent forbids `strict=True` on cross-wave reds).

## Pinned module surface (W2)

| Symbol | Module | Role |
| --- | --- | --- |
| `BROKER_BIND_HOST` | `mergecraft.security.broker` | Loopback bind (`127.0.0.1`, D1) |
| `CredentialBrokerConfig` | `mergecraft.security.broker` | Upstream URL, real key, per-run allow-list |
| `CredentialBrokerHandle` | `mergecraft.security.broker` | `host`, `port`, `token`, `base_url` |
| `credential_broker` | `mergecraft.security.broker` | Context manager — start/stop API |
| `redact_broker_output` | `mergecraft.security.broker` | Redact responses/errors/logs (#553) |
| `resolve_codex_broker_posture` | `mergecraft.security.broker` | Subscription vs API-key posture (D3a) |
| `broker_run_record_fields` | `mergecraft.security.broker` | Run-record disclosure helper (D3a/D10) |
| `CODEX_BROKER_BEARER_ENV` | `mergecraft.security.broker` | Throwaway bearer env-var name (D2) |

## Pinned module surface (W3)

| Symbol | Module | Role |
| --- | --- | --- |
| `prepare_codex_brokered_run` | `mergecraft.agents.codex` | Start broker → `_build_env` → auth → MCP config |

## W1.1 — credential broker (greening wave W2)

| Contract | Test |
| --- | --- |
| Bind `127.0.0.1` only; `BROKER_BIND_HOST` pinned | `test_broker_binds_loopback_only` |
| Forcing `0.0.0.0` fails | `test_broker_rejects_non_loopback_bind` |
| No bearer → 401 | `test_broker_rejects_missing_bearer` |
| Wrong bearer → 401 | `test_broker_rejects_wrong_bearer` |
| Constant-time `compare_digest` | `test_bearer_validation_uses_constant_time_compare_digest` |
| `Host` / `X-Forwarded-Host` smuggle → 403 | `test_broker_rejects_upstream_host_smuggle` |
| Absolute URL rewrite → 403 | `test_broker_rejects_absolute_url_rewrite` (uses `post_absolute_url_to_broker` — httpx origin-form bypass) |
| Redirect off allow-list refused | `test_broker_refuses_redirect_to_non_allowlisted_host` |
| Non-model paths refused (D4) | `test_broker_refuses_non_model_paths` |
| Real key absent from bodies/errors/logs | `test_broker_never_leaks_real_credential_in_responses_errors_or_logs` |
| Real key absent from evidence-packet fixture | `test_broker_never_leaks_real_credential_in_evidence_packet_fixture` |
| Parent→upstream `Authorization` uses real key | `test_broker_forwards_real_key_on_parent_upstream_leg` |
| Concurrent requests with same bearer | `test_concurrent_requests_with_same_bearer` |
| No credentials → `auth_mode=none` (D3a) | `test_resolve_codex_broker_posture_no_credentials` |
| API key without subscription → active (D3a) | `test_resolve_codex_broker_posture_api_key_active` |
| Usable subscription → inactive (D3a) | `test_resolve_codex_broker_posture_subscription_not_brokered` |
| Disallowed HTTP methods → 405 | `test_broker_rejects_put_method` |
| Subscription token-shape branches (D3a) | `test_subscription_auth_usable_shapes` |
| Run-record posture serialization (D3a/D10) | `test_broker_run_record_fields_serializes_posture` |

Guard-deletion note: auth tests assert **401** on missing/wrong bearer — permissive 200 would fail.

## W1.2 — Codex wire-up (greening wave W3)

| Contract | Test |
| --- | --- |
| Agent env: throwaway bearer, no live `OPENAI_API_KEY` | `test_brokered_agent_env_carries_throwaway_not_live_openai_key` |
| `auth.json` has no real API credential after chown (D3) | `test_auth_json_contains_no_real_api_credential_after_setup_and_chown` |
| `model_providers.<id>.base_url` → loopback broker | `test_model_providers_base_url_points_at_loopback_broker` |
| MCP table unchanged | `test_mcp_table_unchanged_under_broker` |
| `CODEX_AUTH_JSON` → broker inactive + run record (D3a) | `test_subscription_auth_marks_broker_inactive_and_run_record_says_so` |
| Subscription path leaves `auth.json` untouched (D3a) | `test_subscription_auth_leaves_auth_json_untouched` |
| Broker start failure: no silent key re-injection (D10) | `test_broker_start_failure_does_not_silently_reinject_openai_key` |
| `_build_env` does not reference lane-B symbols (D8) | `test_build_env_does_not_reference_lane_b_sandbox_symbols` |
| `prepare_codex_brokered_run` does not reference lane-B symbols (D8) | `test_prepare_codex_brokered_run_does_not_reference_lane_b_sandbox_symbols` |
| Lane-B symbols remain in `codex.py` (D8) | `test_lane_b_sandbox_symbols_remain_defined_in_codex_module` |

## W4 reconciliation — AG9 trunk guard

| Fix | Rationale |
| --- | --- |
| `test_no_caller_signature_changed` exempts `codex.py` | Lane E W3 legitimately changed `codex.py` for broker wire-up; AG9 guard (`test_gateway_settings_reuse.py`) now pins only `opencode.py`. Codex broker contracts stay in `test_codex_credential_broker.py`. |
| `test_claim_sink_handoff` binds telemetry `on` before OTLP | Full-suite xdist workers can inherit enterprise opt-out; explicit `bind_enterprise_from_settings(telemetry="on")` prevents `NullSink` degradation during coverage-gate. |

## Contract → files

| Greening wave | Test file |
| --- | --- |
| W2 | `tests/security/test_credential_broker.py` |
| W2 | `tests/security/support_agent_isolation.py` |
| W3 | `tests/agents/test_codex_credential_broker.py` |
| W3 | `tests/agents/support_codex_credential_broker.py` |

## Fixture credential

`REAL_OPENAI_API_KEY_FIXTURE` (`sk-live-run-fixture-openai-never-leak-18`) is the planted parent key for redaction and env assertions. It must never appear in broker outputs, agent env, `auth.json`, logs, or serialized evidence fixtures.
