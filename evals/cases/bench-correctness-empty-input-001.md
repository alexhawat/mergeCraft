---
id: bench-correctness-empty-input-001
title: Missing empty-input guard in first_case_id must block merge
category: missed_finding
submitted_at: '2026-08-15T13:23:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/evals/first_case.py:7 empty list indexed without
  a guard
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-empty-input-001
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:23:00.000000Z'
recorded_findings:
- path: src/mergecraft/evals/first_case.py
  start_line: 7
  end_line: 7
  message: first_case_id drops the empty-list guard; case_ids[0] now raises on an
    empty corpus
  severity: Major
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessEmptyInput00101
  tool: agent
  rule_id: agent:bench-correctness-empty-input-001
  introduced_by_pr: 'true'
  evidence:
  - first_case_id([]) raises IndexError instead of returning a sentinel
  remediation: 'Restore `if not case_ids: return ""` before indexing.'
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Edge-case class — an empty input list must not crash a function that indexes into it.
