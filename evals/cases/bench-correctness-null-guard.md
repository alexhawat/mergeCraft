---
id: bench-correctness-null-guard
title: Missing null guard on optional config must block merge
category: missed_finding
submitted_at: '2026-08-13T12:01:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/config/loader.py:44 optional field dereferenced without check
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-null-guard
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:01:00.000000Z'
recorded_findings:
- path: src/mergecraft/config/loader.py
  start_line: 44
  end_line: 48
  message: Optional nested key accessed without guard when parent may be absent
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCorrectNullGuard01
  tool: agent
  rule_id: agent:bench-correctness-null-guard
  introduced_by_pr: 'true'
  evidence:
  - settings.analyzers may be None on minimal configs
  remediation: Guard optional parent before nested access or use default factory.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). Correctness class — optional config paths must not
crash at load time on minimal repos.
