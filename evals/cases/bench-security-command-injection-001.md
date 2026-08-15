---
id: bench-security-command-injection-001
title: Command injection via shell=True must block merge
category: missed_finding
submitted_at: '2026-08-15T13:11:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/prep/toolchain.py:9-11 command injection via shell=True
expected_decision: failure
replay_command: mergecraft eval replay bench-security-command-injection-001
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:11:00.000000Z'
recorded_findings:
- path: src/mergecraft/prep/toolchain.py
  start_line: 9
  end_line: 11
  message: tool_version switched to shell=True with the tool name interpolated into
    the command string
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityCommandInjection00101
  tool: agent
  rule_id: agent:bench-security-command-injection-001
  introduced_by_pr: 'true'
  evidence:
  - tool_name = 'ruff; rm -rf /' executes an arbitrary shell command
  remediation: Pass an argv list without shell=True, as before.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — shell=True on caller-controlled input is command injection regardless of intent.
