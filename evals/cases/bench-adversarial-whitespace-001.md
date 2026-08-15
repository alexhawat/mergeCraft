---
id: bench-adversarial-whitespace-001
title: Whitespace-only diff must not self-approve as blocked
category: false_positive
submitted_at: '2026-08-15T13:27:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on a trailing-whitespace-only diff
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-whitespace-001
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:27:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Adversarial/no-op — trailing whitespace removed and a trailing newline added; no functional change, no findings expected.
