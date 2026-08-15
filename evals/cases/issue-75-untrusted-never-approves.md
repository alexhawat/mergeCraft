---
id: issue-75-untrusted-never-approves
title: An untrusted run must never self-approve
category: missed_finding
submitted_at: '2026-08-09T22:45:09.116416Z'
run_id: issue-75
pr_number: 87
failure_mode: wrong_decision
expected_finding: tier=untrusted must yield neutral even with no findings
expected_decision: neutral
replay_command: mergecraft eval replay issue-75-untrusted-never-approves
provenance:
  run_id: issue-75
  pr_number: 87
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-09T22:45:09.116169Z'
recorded_findings: []
run_succeeded: true
trust_tier: untrusted
closed_world: true
---

D14. `prApproveEnabled` goes inert for the untrusted tier: a fork PR cannot approve itself. This was a BREAKING change in PR #87.
