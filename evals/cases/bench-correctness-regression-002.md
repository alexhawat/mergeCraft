---
id: bench-correctness-regression-002
title: Reintroduced double-execution regression must block merge
category: missed_finding
submitted_at: '2026-08-15T13:22:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/retry.py:17-18 previously-fixed double-execution
  bug reintroduced
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-regression-002
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:22:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/retry.py
  start_line: 17
  end_line: 18
  message: 'fn() is called twice again — once to check truthiness, once to return
    — exactly the bug the #94 comment documents as fixed'
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessRegression00201
  tool: agent
  rule_id: agent:bench-correctness-regression-002
  introduced_by_pr: 'true'
  evidence:
  - A side-effecting fn (e.g. incrementing a counter) now runs twice per successful
    attempt
  remediation: Cache the result of a single fn() call and return it, as the comment
    describes.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Regression class — the exact double-call pattern an in-code comment documents as fixed by #94 was reintroduced.
