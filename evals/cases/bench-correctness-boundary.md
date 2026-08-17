---
id: bench-correctness-boundary
title: Off-by-one page boundary must be flagged as a blocker
category: missed_finding
submitted_at: '2026-08-15T13:05:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/pagination.py:9 boundary reads one item past
  the page edge
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-boundary
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:05:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/pagination.py
  start_line: 9
  end_line: 9
  message: 'Off-by-one: end bound is start + page_size + 1, leaking one item from
    the next page'
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessBoundary01
  tool: agent
  rule_id: agent:bench-correctness-boundary
  introduced_by_pr: 'true'
  evidence:
  - page_slice(items, 0, 10) returns 11 items instead of 10
  remediation: Use end = start + page_size.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Correctness class — an off-by-one slice bound silently leaks a row from the next page.
