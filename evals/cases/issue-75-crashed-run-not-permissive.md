---
id: issue-75-crashed-run-not-permissive
title: A crashed run must never be permissive
category: missed_finding
submitted_at: '2026-08-09T22:45:08.733176Z'
run_id: issue-75
pr_number: 87
failure_mode: wrong_decision
expected_finding: run_succeeded=False must yield neutral, not success
expected_decision: neutral
replay_command: mergecraft eval replay issue-75-crashed-run-not-permissive
provenance:
  run_id: issue-75
  pr_number: 87
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-09T22:45:08.732882Z'
recorded_findings: []
run_succeeded: false
trust_tier: trusted
---

D13. A run that crashed produced no evidence, so it cannot produce a positive verdict. Before PR #87 a preserved approval could survive a later failure.
