---
id: bench-adversarial-suspicious-003
title: Large purely-additive data diff must not self-approve as blocked
category: false_positive
submitted_at: '2026-08-15T13:36:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on a large but purely-additive data-table diff
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-suspicious-003
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:36:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Adversarial — the diff looks large enough to warrant scrutiny, but every added line is a static data-table entry with no control flow; no findings expected.
