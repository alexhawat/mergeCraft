---
id: bench-crossfile-api-signature
title: Public API signature change without updating callers must block
category: missed_finding
submitted_at: '2026-08-13T12:03:00.000000Z'
run_id: bench-crossfile
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/action/runner.py:210 caller still passes old arity after export change
expected_decision: failure
replay_command: mergecraft eval replay bench-crossfile-api-signature
provenance:
  run_id: bench-crossfile
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:03:00.000000Z'
recorded_findings:
- path: src/mergecraft/action/runner.py
  start_line: 210
  end_line: 215
  message: Call site not updated after run_review gained required trust_tier argument
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCrossfileSig01
  tool: agent
  rule_id: agent:bench-crossfile-api-signature
  introduced_by_pr: 'true'
  evidence:
  - TypeError at runtime when optional argument removed from callee
  remediation: Update all in-repo call sites or provide backward-compatible shim.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). Cross-file breakage — signature drift across package
boundaries must surface as a blocker.
