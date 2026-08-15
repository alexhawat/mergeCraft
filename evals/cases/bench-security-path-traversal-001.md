---
id: bench-security-path-traversal-001
title: Dropped path-traversal containment check must block merge
category: missed_finding
submitted_at: '2026-08-15T13:13:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/artifact_fetch.py:9-10 path-traversal containment
  check removed
expected_decision: failure
replay_command: mergecraft eval replay bench-security-path-traversal-001
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:13:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/artifact_fetch.py
  start_line: 9
  end_line: 10
  message: resolve_artifact no longer checks that the resolved path stays under results_dir
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityPathTraversal00101
  tool: agent
  rule_id: agent:bench-security-path-traversal-001
  introduced_by_pr: 'true'
  evidence:
  - requested = '../../../../etc/passwd' now resolves outside results_dir
  remediation: Restore the is_relative_to containment check before returning.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — removing the containment check lets a caller-supplied path escape the results directory.
