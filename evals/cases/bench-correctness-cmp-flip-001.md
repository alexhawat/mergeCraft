---
id: bench-correctness-cmp-flip-001
title: Quota check flipped >= to > must be flagged as a blocker
category: missed_finding
submitted_at: '2026-08-15T13:01:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/quota.py:8 comparison operator flipped from
  >= to >
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-cmp-flip-001
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:01:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/quota.py
  start_line: 8
  end_line: 8
  message: Comparison flipped from >= to > — usage exactly at the limit is no longer
    flagged
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessCmpFlip00101
  tool: agent
  rule_id: agent:bench-correctness-cmp-flip-001
  introduced_by_pr: 'true'
  evidence:
  - is_over_budget(limit, limit) now returns False
  remediation: Restore the inclusive >= comparison.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Correctness class — a flipped comparison operator that changes boundary behavior must surface as a Critical blocker.
