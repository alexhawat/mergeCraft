---
id: bench-security-auth-removed-001
title: Removed webhook signature verification must block merge
category: missed_finding
submitted_at: '2026-08-15T13:15:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/action/webhook.py:9 webhook signature verification
  removed
expected_decision: failure
replay_command: mergecraft eval replay bench-security-auth-removed-001
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:15:00.000000Z'
recorded_findings:
- path: src/mergecraft/action/webhook.py
  start_line: 9
  end_line: 9
  message: handle_webhook no longer verifies the HMAC signature before returning True
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityAuthRemoved00101
  tool: agent
  rule_id: agent:bench-security-auth-removed-001
  introduced_by_pr: 'true'
  evidence:
  - Any payload with any signature (or none) is accepted as authentic
  remediation: Restore the hmac.compare_digest check before returning True.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — an authentication check removed so the function unconditionally accepts every input is always a blocker.
