---
id: bench-correctness-resource-leak-001
title: Unclosed file handle in read_scratch must block merge
category: missed_finding
submitted_at: '2026-08-15T13:07:00.000000Z'
run_id: bench-correctness
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/utils/tempfiles.py:17 file handle opened without
  being closed
expected_decision: failure
replay_command: mergecraft eval replay bench-correctness-resource-leak-001
provenance:
  run_id: bench-correctness
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-15T13:07:00.000000Z'
recorded_findings:
- path: src/mergecraft/utils/tempfiles.py
  start_line: 17
  end_line: 17
  message: read_scratch opens the file handle without a context manager or explicit
    close
  severity: Major
  confidence: certain
  category: Stability & Availability
  source: agent
  fingerprint: benchCorrectnessResourceLeak00101
  tool: agent
  rule_id: agent:bench-correctness-resource-leak-001
  introduced_by_pr: 'true'
  evidence:
  - Every call to read_scratch leaks a file descriptor
  remediation: Use `with path.open(...) as handle:` as write_scratch does.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Agent-seeded corpus case (B4). Resource-handling class — a file handle opened without a context manager leaks a descriptor on every call.
