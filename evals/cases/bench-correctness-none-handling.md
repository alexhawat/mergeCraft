---
id: bench-correctness-none-handling
title: Missing None guard on optional gate config must block merge
category: missed_finding
submitted_at: '2026-08-15T13:06:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/config/threshold.py:10-11 optional config section
  dereferenced without a guard
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-none-handling
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:06:00.000000Z'
recorded_findings:
- path: src/mergecraft/config/threshold.py
  start_line: 10
  end_line: 11
  message: Optional 'gate' config section accessed without a None guard when absent
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessNoneHandling01
  tool: agent
  rule_id: agent:bench-correctness-none-handling
  introduced_by_pr: 'true'
  evidence:
  - config.get('gate') returns None on a minimal .mergecraft/config.yaml, then .get
    raises AttributeError
  remediation: Guard with `or {}` (or default_factory) before calling .get on the
    section.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Correctness class — a minimal repo config with no gate section must not crash config resolution.
