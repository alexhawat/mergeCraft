---
id: bench-correctness-empty-input-002
title: Missing empty-input guard in mean_score must block merge
category: missed_finding
submitted_at: '2026-08-15T13:24:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/evals/mean_score.py:7 division by zero-length list
  without a guard
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-empty-input-002
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:24:00.000000Z'
recorded_findings:
- path: src/mergecraft/evals/mean_score.py
  start_line: 7
  end_line: 7
  message: mean_score drops the empty-list guard; dividing by len(scores) now raises
    ZeroDivisionError on an empty list
  severity: Major
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessEmptyInput00201
  tool: agent
  rule_id: agent:bench-correctness-empty-input-002
  introduced_by_pr: 'true'
  evidence:
  - mean_score([]) raises ZeroDivisionError instead of returning 0.0
  remediation: 'Restore `if not scores: return 0.0` before dividing.'
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Edge-case class — an empty scores list must not crash a mean calculation via division by zero.
