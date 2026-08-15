---
id: bench-crossfile-signature-stale
title: Stale call site after a signature change must block merge
category: missed_finding
submitted_at: '2026-08-15T13:17:00.000000Z'
run_id: bench-crossfile
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/analyzers/pipeline.py:13 caller still passes old
  arity after signature change
expected_decision: failure
replay_command: mergecraft eval replay bench-crossfile-signature-stale
provenance:
  run_id: bench-crossfile
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:17:00.000000Z'
recorded_findings:
- path: src/mergecraft/analyzers/pipeline.py
  start_line: 13
  end_line: 13
  message: register_adapter gained a required trust_tier kwarg in registry.py; this
    call site was not updated
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCrossfileSignatureStale01
  tool: agent
  rule_id: agent:bench-crossfile-signature-stale
  introduced_by_pr: 'true'
  evidence:
  - 'TypeError: register_adapter() missing 1 required keyword-only argument: ''trust_tier'''
  remediation: Pass trust_tier explicitly at every register_adapter call site.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Cross-file breakage — a required kwarg added to an adapter-registry function without updating every in-repo call site.
