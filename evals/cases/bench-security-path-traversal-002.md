---
id: bench-security-path-traversal-002
title: Path traversal via unsanitized export name must block merge
category: missed_finding
submitted_at: '2026-08-15T13:14:00.000000Z'
run_id: bench-security
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/cli/export_cmd.py:11 path traversal via unsanitized
  report name
expected_decision: failure
replay_command: mergecraft eval replay bench-security-path-traversal-002
provenance:
  run_id: bench-security
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:14:00.000000Z'
recorded_findings:
- path: src/mergecraft/cli/export_cmd.py
  start_line: 11
  end_line: 11
  message: export_report drops the Path(name).name sanitization and joins the raw
    caller-supplied name
  severity: Critical
  confidence: certain
  category: Security & Privacy
  source: agent
  fingerprint: benchSecurityPathTraversal00201
  tool: agent
  rule_id: agent:bench-security-path-traversal-002
  introduced_by_pr: 'true'
  evidence:
  - name = '../../.env' resolves outside _REPORTS_DIR
  remediation: Restore `safe_name = Path(name).name` before joining.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Security class — joining a raw caller-supplied filename without stripping directory components enables path traversal.
