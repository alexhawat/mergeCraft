---
id: bench-correctness-wrong-var-002
title: weighted_score summing the wrong variable must be flagged as a blocker
category: missed_finding
submitted_at: '2026-08-15T13:04:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/analyzers/severity.py:10 wrong variable used in weighted_score's
  sum
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-wrong-var-002
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:04:00.000000Z'
recorded_findings:
- path: src/mergecraft/analyzers/severity.py
  start_line: 10
  end_line: 10
  message: weighted_score sums critical_weight twice — major_weight never contributes
    to the total
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessWrongVar00201
  tool: agent
  rule_id: agent:bench-correctness-wrong-var-002
  introduced_by_pr: 'true'
  evidence:
  - major_count is computed but discarded; the return only uses critical_weight
  remediation: Return critical_weight + major_weight.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Correctness class — copy-paste of the wrong local variable silently drops an entire term from a computed score.
