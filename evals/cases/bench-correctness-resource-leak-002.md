---
id: bench-correctness-resource-leak-002
title: Unclosed httpx.Client in fetch_log must block merge
category: missed_finding
submitted_at: '2026-08-15T13:08:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/ci/log_fetch.py:9 httpx.Client opened without being
  closed
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-resource-leak-002
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:08:00.000000Z'
recorded_findings:
- path: src/mergecraft/ci/log_fetch.py
  start_line: 9
  end_line: 9
  message: fetch_log drops the `with httpx.Client()` context manager — the client
    and its connection pool are never closed
  severity: Major
  confidence: certain
  category: Stability & Availability
  source: agent
  fingerprint: benchCorrectnessResourceLeak00201
  tool: agent
  rule_id: agent:bench-correctness-resource-leak-002
  introduced_by_pr: 'true'
  evidence:
  - Repeated calls to fetch_log accumulate open sockets under load
  remediation: Restore `with httpx.Client() as client:` or reuse a module-level client.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Resource-handling class — dropping the client context manager leaks a connection pool on every call.
