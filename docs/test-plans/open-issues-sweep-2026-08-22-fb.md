# Open issues sweep 2026-08-22 — Batch FB test plan (#400 #398)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md`
Worktree: `.ignorelocal/worktrees/repo-state-2026-08-22-sweep` @ `wave/repo-state-2026-08-22-sweep`
Authoring wave: **W3** (FB RED) · Implementation: **W4** (`agent_protocol.py` dead else + `audit.py` JSONL skip)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W4** | `test_load_audit_events_skips_malformed_and_non_dict_lines` | `green after W4: skip malformed audit JSONL lines (#398)` | pending — **XFAIL** (malformed line raises `JSONDecodeError` today) |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| FB400a | Unknown negotiation tokens raise `ProtocolNegotiationError` | unit | error | `tests/cli/test_fb_protocol_negotiation.py::test_negotiate_protocol_rejects_unknown_tokens` |
| FB400b | `schema_version` field token selects `CLI_JSON_SCHEMA_VERSION` via explicit branch | unit | happy | `tests/cli/test_fb_protocol_negotiation.py::test_negotiate_protocol_schema_version_field_token` |
| FB400c | `protocol_version` field token selects `AGENT_PROTOCOL_VERSION` via explicit branch | unit | happy | `tests/cli/test_fb_protocol_negotiation.py::test_negotiate_protocol_protocol_version_field_token` |
| FB400d | Literal `1` / `1.0.0` version strings still negotiate | unit | happy | `test_negotiate_protocol_literal_agent_version`, `test_negotiate_protocol_literal_cli_schema_version` |
| FB400e | When both literals overlap, agent wire version wins | unit | edge | `test_negotiate_protocol_prefers_agent_when_both_literals_offered` |
| FB400f | Tests do not require unreachable `else` alias lookup (D8) | design | — | FB module uses only explicit-branch tokens and literals; no alias-table-only offers |
| FB398a | `load_audit_events` returns only dict payloads from mixed JSONL | unit | happy | `tests/enterprise/test_audit.py::test_load_audit_events_skips_malformed_and_non_dict_lines` |
| FB398b | Malformed JSONL line does not abort load (D9 skip policy) | unit | error | same (XFAIL until W4) |
| FB398c | Non-dict JSON payload is skipped, not appended | unit | edge | same |

## W3 RED evidence

- **#400** — negotiation contracts pass today (regression guards for W4 dead-code removal); no xfail.
- **#398** — `load_audit_events` on mixed file raises `JSONDecodeError` on malformed line → **XFAIL**.

## Out of scope

- `tracing/sinks.py` `read_jsonl_events` (read-only precedent for D9).
- `cli/app.py` root callback.
