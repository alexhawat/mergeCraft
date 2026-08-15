---
id: bench-correctness-wrong-var-001
title: average_recall using the wrong accumulator must be flagged as a blocker
category: missed_finding
submitted_at: '2026-08-15T13:03:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/evals/aggregate.py:10 wrong variable used in average_recall's
  division
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-wrong-var-001
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:03:00.000000Z'
recorded_findings:
- path: src/mergecraft/evals/aggregate.py
  start_line: 10
  end_line: 10
  message: average_recall divides total_precision, not total_recall — returns the
    wrong metric
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessWrongVar00101
  tool: agent
  rule_id: agent:bench-correctness-wrong-var-001
  introduced_by_pr: 'true'
  evidence:
  - Function name and docstring promise recall; the body returns mean precision instead
  remediation: Divide total_recall, not total_precision, by count.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Correctness class — using the wrong accumulator variable silently swaps one metric for another.
