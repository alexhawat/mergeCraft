---
id: bench-security-hardcoded-token
title: Hard-coded API token in source must block merge
category: missed_finding
submitted_at: '2026-08-13T12:02:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: scripts/debug_client.py:12 literal bearer token committed
expected_decision: failure
replay_command: mergecraft eval replay bench-security-hardcoded-token
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:02:00.000000Z'
recorded_findings:
- path: scripts/debug_client.py
  start_line: 12
  end_line: 12
  message: Bearer token literal committed to the repository
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityToken01
  tool: agent
  rule_id: agent:bench-security-hardcoded-token
  introduced_by_pr: 'true'
  evidence:
  - Authorization header uses sk- prefixed secret material inline
  remediation: Load from environment or secret manager; rotate exposed credential.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). Security class — secrets in tree are always blockers.
