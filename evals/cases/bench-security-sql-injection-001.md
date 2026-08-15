---
id: bench-security-sql-injection-001
title: SQL built via f-string interpolation must block merge
category: missed_finding
submitted_at: '2026-08-15T13:09:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/ci/db.py:9-10 SQL injection via unparameterized query
expected_decision: failure
replay_command: mergecraft eval replay bench-security-sql-injection-001
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:09:00.000000Z'
recorded_findings:
- path: src/mergecraft/ci/db.py
  start_line: 9
  end_line: 10
  message: find_run interpolates run_id directly into the SQL string instead of using
    a parameter
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecuritySqlInjection00101
  tool: agent
  rule_id: agent:bench-security-sql-injection-001
  introduced_by_pr: 'true'
  evidence:
  - run_id = "' OR '1'='1" returns every row in the table
  remediation: 'Use the parameterized form: conn.execute(sql, (run_id,)).'
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — string-built SQL queries on caller-controlled input are always a blocker.
