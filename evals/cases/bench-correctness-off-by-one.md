---
id: bench-correctness-off-by-one
title: Off-by-one loop bound must be flagged as a blocker
category: missed_finding
submitted_at: '2026-08-13T12:00:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/range.py:18-22 boundary reads past end
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-off-by-one
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:00:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/range.py
  start_line: 18
  end_line: 22
  message: Loop uses inclusive upper bound where slice is exclusive
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectOffByOne01
  tool: agent
  rule_id: agent:bench-correctness-off-by-one
  introduced_by_pr: 'true'
  evidence:
  - range(len(items)+1) indexes one past the last element
  remediation: Use half-open interval or len(items) as upper bound.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). A trusted run with a Critical correctness finding
must yield ``failure`` — the structural gate blocks on Critical/Major findings.
