---
id: bench-crossfile-config-rename-002
title: Stale tracing-client consumer after a config rename must block merge
category: missed_finding
submitted_at: '2026-08-15T13:19:00.000000Z'
run_id: bench-crossfile
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/ci/tracing_client.py:14 consumer still reads the
  renamed tracing field's old name
expected_decision: failure
replay_command: mergecraft eval replay bench-crossfile-config-rename-002
provenance:
  run_id: bench-crossfile
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:19:00.000000Z'
recorded_findings:
- path: src/mergecraft/ci/tracing_client.py
  start_line: 14
  end_line: 14
  message: TracingSettings renamed otlp_endpoint to exporter_endpoint; build_client
    still reads the old field name
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCrossfileConfigRename00201
  tool: agent
  rule_id: agent:bench-crossfile-config-rename-002
  introduced_by_pr: 'true'
  evidence:
  - 'AttributeError: ''TracingSettings'' object has no attribute ''otlp_endpoint'''
  remediation: Update build_client to read settings.exporter_endpoint.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Cross-file breakage — a tracing config field renamed in its schema without updating the client that builds from it.
