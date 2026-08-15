---
id: bench-correctness-concurrency-002
title: Dropped lock around shared cache access must block merge
category: missed_finding
submitted_at: '2026-08-15T13:26:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/ci/cache.py:11-12 shared mutable state accessed without
  the lock
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-concurrency-002
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:26:00.000000Z'
recorded_findings:
- path: src/mergecraft/ci/cache.py
  start_line: 11
  end_line: 12
  message: get_or_compute no longer takes _LOCK before checking/writing the shared
    cache dict — a race under concurrent tasks
  severity: Critical
  confidence: certain
  category: Stability & Availability
  source: agent
  fingerprint: benchCorrectnessConcurrency00201
  tool: agent
  rule_id: agent:bench-correctness-concurrency-002
  introduced_by_pr: 'true'
  evidence:
  - Two concurrent calls for the same key can both miss the cache and both call compute()
  remediation: Restore `async with _LOCK:` around the check-then-write.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Concurrency class — dropping the lock around a shared cache dict's check-then-write reintroduces a race under concurrent tasks.
