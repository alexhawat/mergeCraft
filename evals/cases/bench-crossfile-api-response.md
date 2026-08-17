---
id: bench-crossfile-api-response
title: Stale caller after an API response shape change must block merge
category: missed_finding
submitted_at: '2026-08-15T13:20:00.000000Z'
run_id: bench-crossfile
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/cli/pipeline_cmd.py:12 caller still assumes the old
  list-shaped API response
expected_decision: failure
replay_command: mergecraft eval replay bench-crossfile-api-response
provenance:
  run_id: bench-crossfile
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:20:00.000000Z'
recorded_findings:
- path: src/mergecraft/cli/pipeline_cmd.py
  start_line: 12
  end_line: 12
  message: 'run_pipeline now returns {''findings'': [...], ''meta'': {...}}; print_findings
    still iterates it as a bare list of Finding'
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCrossfileApiResponse01
  tool: agent
  rule_id: agent:bench-crossfile-api-response
  introduced_by_pr: 'true'
  evidence:
  - Iterating a dict yields its string keys, so `finding.message` raises AttributeError
  remediation: Update print_findings to iterate result['findings'].
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Cross-file breakage — a function's return shape changed from a list to a dict envelope without updating an in-repo caller.
