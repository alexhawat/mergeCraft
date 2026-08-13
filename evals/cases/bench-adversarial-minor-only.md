---
id: bench-adversarial-minor-only
title: Minor hygiene finding alone must not block merge
category: false_positive
submitted_at: '2026-08-13T12:06:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: Minor typo in comment must not yield failure verdict
expected_decision: success
replay_command: mergecraft eval replay bench-adversarial-minor-only
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:06:00.000000Z'
recorded_findings:
- path: docs/CONTRIBUTING.md
  start_line: 40
  end_line: 40
  message: Comment uses British spelling where project style prefers American
  severity: Minor
  confidence: possible
  category: Maintainability & Code Quality
  source: agent
  fingerprint: benchAdversarialMinor01
  tool: agent
  rule_id: agent:bench-adversarial-minor-only
  introduced_by_pr: 'false'
  evidence:
  - Non-blocking hygiene nit only
  remediation: Optional style fix; not a merge gate.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). Adversarial/no-op — only Critical/Major findings block;
Minor-only output must not regress to ``failure``.
