---
id: bench-adversarial-refactor-001
title: Behavior-preserving variable rename must not self-approve as blocked
category: false_positive
submitted_at: '2026-08-15T13:30:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on a variable-rename-only refactor
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-refactor-001
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:30:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Adversarial/no-op — every renamed local variable keeps the same value and control flow; purely cosmetic, no findings expected.
