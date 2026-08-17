---
id: bench-adversarial-suspicious-002
title: Standard HTTP status-code special-case must not self-approve as blocked
category: false_positive
submitted_at: '2026-08-15T13:35:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on a special-cased standard HTTP status code
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-suspicious-002
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:35:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Adversarial — `429` looks like an unexplained magic number, but it is the standard HTTP Too Many Requests status; the shorter backoff is a deliberate choice for that one case, not a defect.
