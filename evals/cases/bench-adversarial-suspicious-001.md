---
id: bench-adversarial-suspicious-001
title: Documented broad except in best-effort telemetry must not self-approve as blocked
category: false_positive
submitted_at: '2026-08-15T13:34:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on a deliberate, documented broad except in a best-effort
  path
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-suspicious-001
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:34:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Adversarial — a bare `except Exception` looks suspicious in isolation, but this function's own docstring specifies it must never crash its caller; the broad catch is correct and intentional, not a bug.
