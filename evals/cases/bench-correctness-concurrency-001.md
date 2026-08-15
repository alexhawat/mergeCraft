---
id: bench-correctness-concurrency-001
title: Missing await on an async send call must block merge
category: missed_finding
submitted_at: '2026-08-15T13:25:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/ci/notify.py:10 missing await on an async call
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-concurrency-001
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:25:00.000000Z'
recorded_findings:
- path: src/mergecraft/ci/notify.py
  start_line: 10
  end_line: 10
  message: notify_all no longer awaits hook.send(), firing notifications without waiting
    for completion
  severity: Critical
  confidence: certain
  category: Stability & Availability
  source: agent
  fingerprint: benchCorrectnessConcurrency00101
  tool: agent
  rule_id: agent:bench-correctness-concurrency-001
  introduced_by_pr: 'true'
  evidence:
  - A coroutine object is created and immediately discarded; notifications may never
    actually send
  remediation: Restore the `await` on hook.send().
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Concurrency class — a dropped `await` on an async call creates an unawaited coroutine instead of running it.
