---
id: bench-correctness-cmp-flip-002
title: Retry exhaustion check flipped >= to > must be flagged as a blocker
category: missed_finding
submitted_at: '2026-08-15T13:02:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/ci/flaky.py:12 comparison operator flipped from >=
  to >
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-cmp-flip-002
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:02:00.000000Z'
recorded_findings:
- path: src/mergecraft/ci/flaky.py
  start_line: 12
  end_line: 12
  message: Comparison flipped from >= to > — retry loop runs one extra attempt past
    max_attempts
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessCmpFlip00201
  tool: agent
  rule_id: agent:bench-correctness-cmp-flip-002
  introduced_by_pr: 'true'
  evidence:
  - is_exhausted(max_attempts, max_attempts) now returns False
  remediation: Restore the inclusive >= comparison.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Correctness class — retry-exhaustion boundary must be exact; an off-by-one here silently allows unbounded extra retries.
