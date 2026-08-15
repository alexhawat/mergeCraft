---
id: bench-security-sql-injection-002
title: SQL built via string concatenation must block merge
category: missed_finding
submitted_at: '2026-08-15T13:10:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/learnings/store.py:10 SQL injection via string concatenation
expected_decision: failure
replay_command: mergecraft eval replay bench-security-sql-injection-002
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:10:00.000000Z'
recorded_findings:
- path: src/mergecraft/learnings/store.py
  start_line: 10
  end_line: 10
  message: learnings_for_repo concatenates repo_slug into the SQL string instead of
    binding it as a parameter
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecuritySqlInjection00201
  tool: agent
  rule_id: agent:bench-security-sql-injection-002
  introduced_by_pr: 'true'
  evidence:
  - repo_slug = "x' OR '1'='1" returns every repo's learnings
  remediation: Bind repo_slug as a query parameter instead of string concatenation.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — concatenating caller-controlled input into SQL is always a blocker, parameter binding or not.
