---
id: bench-adversarial-clean-diff
title: Clean documentation-only diff must not self-approve as success
category: false_positive
submitted_at: '2026-08-13T12:05:00.000000Z'
run_id: bench-adversarial
pr_number: null
failure_mode: wrong_decision
expected_finding: no blockers on comment-only README edit
expected_decision: neutral
replay_command: mergecraft eval replay bench-adversarial-clean-diff
provenance:
  run_id: bench-adversarial
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:05:00.000000Z'
recorded_findings: []
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). Adversarial/no-op — a trusted run with no findings
and no blockers must stay ``neutral``, not ``success``/``auto_merge`` without
positive attestation beyond an empty finding list.
