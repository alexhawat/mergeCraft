---
id: bench-crossfile-config-rename-001
title: Stale consumer after a config field rename must block merge
category: missed_finding
submitted_at: '2026-08-15T13:18:00.000000Z'
run_id: bench-crossfile
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/agents/gate_config_reader.py:12 consumer still reads
  the renamed config field's old name
expected_decision: failure
replay_command: mergecraft eval replay bench-crossfile-config-rename-001
provenance:
  run_id: bench-crossfile
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:18:00.000000Z'
recorded_findings:
- path: src/mergecraft/agents/gate_config_reader.py
  start_line: 12
  end_line: 12
  message: GateConfig renamed severity_threshold to min_severity; blocking_threshold
    still reads the old field name
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCrossfileConfigRename00101
  tool: agent
  rule_id: agent:bench-crossfile-config-rename-001
  introduced_by_pr: 'true'
  evidence:
  - 'AttributeError: ''GateConfig'' object has no attribute ''severity_threshold'''
  remediation: Update blocking_threshold to read config.min_severity.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Cross-file breakage — a config field renamed in its schema without updating a consumer elsewhere in the package.
