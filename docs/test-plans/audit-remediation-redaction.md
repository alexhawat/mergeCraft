# Audit remediation — lane B redaction & ingress — test plan (BR1)

Wave plan: `.ignorelocal/waves/10-audit-remediation-b-redaction-ingress-wave-plan.md`
Worktree: `../mc-br1-red` @ `wave/br1-redaction-red`
Authoring wave: **BR1** (tests-first). Implementation: **BR2–BR8**.

Locked decisions applied: **D2** (assert secret absence), **D3** (doctests),
**D4** (structural JSON), **D6** (detection floor 20/32/40 + benign list),
**D9** (idempotency before replay rejection), **D11** (bounded reads),
**D12** (per-client transport metadata), **D13** (audit relocation then chain),
**D16** (real zip / real header bytes), **D17** (hypothesis property tests).

## xfail schedule

BR1 ships **plain failing assertions** (no `xfail`) so impl waves green them
directly. Cross-wave reconciliation removes satisfied tests only after the
matching impl PR lands.

| Greening wave | Test files |
| --- | --- |
| BR2 | `tests/tracing/test_redact_cli_argv.py`, `test_redact_attrs_depth.py`, `test_payload_cap.py`, `test_redact_url.py`, `test_redaction_doctests.py` |
| BR3 | `tests/analyzers/test_redact_json.py`, `test_redact_entropy.py` |
| BR4 | `tests/scm/test_webhook_headers.py`, `test_ingress_idempotency.py` |
| BR5 | `tests/ci/test_log_archive_bounds.py`, `test_sarif_bounds.py` |
| BR6 | `tests/security/test_egress_concurrency.py` |
| BR7 | `tests/enterprise/test_audit_location.py`, `test_audit_chain.py`, `tests/mcp/test_ports_identity.py` |
| BR8 | `tests/tracing/test_sentinel_unified.py` |

## Contract → coverage matrix

### BR1.1 — trace redaction (BR2: MCB-02, MCB-03, MCB-28, MCB-31)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_no_secret_survives_a_flagged_argv` | MCB-02 | D2 — flagged argv never leaks canary secrets |
| `test_flagged_value_is_not_doubled` | MCB-02 | Secret absent; single placeholder for `--api-key sk-…` |
| `test_hypothesis_no_secret_ever_follows_a_flag` | MCB-02 | D17 property over flag/value pairs |
| `test_deny_keys_apply_at_depth_1_2_3` | MCB-03 | Deny keys at nesting depths 1–3 |
| `test_deny_keys_apply_through_a_list_of_dicts` | MCB-03 | Lists of dicts cannot bypass deny keys |
| `test_basic_auth_material_is_redacted` | MCB-03 | Basic-auth blob absent from attrs |
| `test_cap_is_bytes_not_characters` | MCB-28 | UTF-8 byte cap, not character count |
| `test_oversize_payload_is_truncated_not_discarded` | MCB-28 | Head preserved + visible truncation marker |
| `test_http_scheme_is_preserved` | MCB-31 | `http://` not rewritten to `https://` |
| `test_module_doctests_pass` | D3 | `mergecraft.tracing.redaction` doctests execute |

### BR1.2 — analyzer redaction (BR3: MCB-04, MCB-26)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_json_output_is_redacted` | MCB-04 | Non-prefixed JSON secret absent |
| `test_redacted_json_still_parses` | D4 | Structural redaction keeps JSON valid |
| `test_jsonl_is_redacted_line_wise` | MCB-04 | JSONL handled per line |
| `test_trufflehog_fixture_canary_never_reaches_persisted_output` | MCB-04 | `assert_no_canary` on persist path |
| `test_detection_rate_at_lengths_20_32_40` | D6 | Statistical floor at lengths 20/32/40 |
| `test_known_benign_strings_are_untouched` | D5/D6 | SHAs / hex / identifiers unchanged |
| `test_hypothesis_high_entropy_tokens_are_redacted` | D17 | Property on long high-entropy tokens |

### BR1.3 — webhook ingress (BR4: MCB-11, MCB-13)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_non_ascii_header_raises_permission_error` | MCB-11 | Exact `PermissionError` for non-ASCII headers |
| `test_empty_and_oversized_headers_are_rejected` | MCB-11 | Blank secret + oversized signature rejected |
| `test_route_never_returns_500_on_an_unauthenticated_path` | D8 | Route maps failures to 4xx |
| `test_redelivery_through_accept_webhook_is_a_duplicate` | D9 | Second ingress call returns `duplicate=True` |
| `test_webhook_ingress_verifies_then_processes_a_valid_payload` | D9 | Escalation BR4: W15 ingress test aligned — redelivery is `duplicate=True`, not replay raise |
| `test_replay_store_evicts_on_ttl` | MCB-13 | TTL eviction frees delivery ids |
| `test_replay_store_is_bounded` | MCB-13 | Store size capped |
| `test_far_future_skew_is_rejected` | MCB-13 | Far-future skew rejected |

### BR1.4 — archive bounds (BR5: MCB-14)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_high_ratio_archive_is_refused` | D16 | Real zip high-ratio expansion bounded |
| `test_member_and_total_caps_are_enforced` | D11 | Per-member and aggregate caps |
| `test_truncation_is_visible_in_the_output` | D11 | Truncation marker visible in log decode |
| `test_sarif_documents_share_the_same_caps` | MCB-14 | SARIF path shares archive caps |

### BR1.5 — egress resolver (BR6: MCB-18)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_overlapping_pins_each_stay_pinned` | MCB-18 | Concurrent pins do not clobber |
| `test_getaddrinfo_is_the_original_object_after_every_test` | MCB-18 | `socket.getaddrinfo` never replaced |
| `test_unrelated_resolution_is_unaffected_by_a_guarded_request` | MCB-18 | Unpinned hosts unchanged |
| `test_host_header_and_sni_survive_ip_pinning` | D12 | `pinned_request_metadata` preserves hostname |

**Escalation (BR6 impl):** `tests/analyzers/test_cov_provision_paths.py::scripted_http`
now mocks `provision.httpx.Client` + `MockTransport` (not legacy `httpx.stream` /
`pin_host_resolution` hooks).

### BR1.6 — audit log and ports (BR7: MCB-21, MCB-27)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_audit_log_is_not_inside_the_workspace` | MCB-21 | Default audit path outside workspace |
| `test_audit_root_env_override_is_honoured` | MCB-21 | `MERGECRAFT_AUDIT_ROOT` honoured |
| `test_verify_detects_a_rewritten_record` | D13 | `verify_audit_chain` detects tamper |
| `test_verify_detects_a_truncated_log` | D13 | Truncation breaks chain |
| `test_squatter_on_the_configured_port_is_not_accepted` | MCB-27 | Port squatter not accepted |
| `test_server_thread_failure_is_raised_not_swallowed` | MCB-27 | Startup failure propagates |

### BR1.7 — sentinel (BR8: MCB-30)

| Test | Finding | Contract |
| --- | --- | --- |
| `test_exactly_one_distinct_sentinel_across_redaction_surfaces` | MCB-30 | One canonical sentinel via `redaction_sentinel` |

## Deliverable symbol grep targets

Impl waves must introduce (or export) at least:

- `mergecraft.redaction_sentinel.REDACTION_SENTINEL` (BR8)
- `mergecraft.security.egress.pinned_request_metadata` (BR6)
- `mergecraft.enterprise.audit.verify_audit_chain` (BR7)
- `mergecraft.scm.webhooks._MAX_DELIVERY_STORE_ENTRIES` (BR4)
- `mergecraft.ci.providers.github_actions._MAX_MEMBER_BYTES` / `_MAX_TOTAL_BYTES` (BR5)
- `mergecraft.ci.intelligence._MAX_MEMBER_BYTES` / `_MAX_TOTAL_BYTES` (BR5)

## Escalation

BR8 census follow-up: harness/config tests (`test_redactor`, `test_diagnostics`, `test_setup_script_failure`) now assert `REDACTION_SENTINEL` (`<redacted>`) instead of legacy `[REDACTED]`.

BR8 integration follow-up: tracing/analyzer adapter tests compare `MemorySink` attrs and parser paths through `as_sink_value` / `finding_path_matches` so BR8 entropy redaction does not false-fail planted-finding and span-identity contracts.

## Escalation (BR7 / MCB-21)

**Escalation:** `test_audit_producer_hk.py` pinned in-workspace `.mergecraft/audit.jsonl` writes; amended to use `MERGECRAFT_AUDIT_ROOT` + `resolve_audit_log_path` after BR7 relocated the audit sink.
