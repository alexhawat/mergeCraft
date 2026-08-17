---
id: bench-correctness-regression-001
title: Reintroduced None-deref regression must block merge
category: missed_finding
submitted_at: '2026-08-15T13:21:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/env_probe.py:12 previously-fixed None-deref
  bug reintroduced
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-regression-001
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:21:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/env_probe.py
  start_line: 12
  end_line: 12
  message: 'The None guard the #118 comment documents was removed; value.strip() now
    raises when MERGECRAFT_REGION is unset'
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectnessRegression00101
  tool: agent
  rule_id: agent:bench-correctness-regression-001
  introduced_by_pr: 'true'
  evidence:
  - os.environ.get returns None when the var is unset; None.strip() raises AttributeError
  remediation: 'Restore the `if value is None: return default` guard.'
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Regression class — a None guard documented by an in-code comment as a prior fix was silently removed, reintroducing the crash.
