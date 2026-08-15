---
id: bench-security-auth-removed-002
title: Removed require_admin authorization check must block merge
category: missed_finding
submitted_at: '2026-08-15T13:16:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/mcp/tools/admin.py:11 authorization check removed
  from reset_learnings
expected_decision: failure
replay_command: mergecraft eval replay bench-security-auth-removed-002
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:16:00.000000Z'
recorded_findings:
- path: src/mergecraft/mcp/tools/admin.py
  start_line: 11
  end_line: 12
  message: reset_learnings no longer calls require_admin before performing a destructive
    reset
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityAuthRemoved00201
  tool: agent
  rule_id: agent:bench-security-auth-removed-002
  introduced_by_pr: 'true'
  evidence:
  - Any caller_role, including a non-admin one, can now trigger _do_reset()
  remediation: Restore the require_admin(caller_role) call at the top of reset_learnings.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — a destructive admin-only tool that drops its authorization guard is always a blocker.
