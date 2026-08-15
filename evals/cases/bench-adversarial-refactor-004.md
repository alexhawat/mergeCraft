---
id: bench-adversarial-refactor-004
title: Loop-to-comprehension refactor must not self-approve as blocked
category: false_positive
submitted_at: '2026-08-15T13:33:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on a loop-to-comprehension refactor
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-refactor-004
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:33:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Adversarial/no-op — a manual accumulation loop replaced by an equivalent list comprehension; no findings expected.
