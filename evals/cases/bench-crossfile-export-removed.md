---
id: bench-crossfile-export-removed
title: Removing a re-export without updating importers must block
category: missed_finding
submitted_at: '2026-08-13T12:04:00.000000Z'
run_id: bench-crossfile
pr_number: null
failure_mode: missed_finding
expected_finding: src/mergecraft/cli/main.py:8 import of removed __all__ symbol
expected_decision: failure
replay_command: mergecraft eval replay bench-crossfile-export-removed
provenance:
  run_id: bench-crossfile
  pr_number: null
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: '2026-08-13T12:04:00.000000Z'
recorded_findings:
- path: src/mergecraft/cli/main.py
  start_line: 8
  end_line: 8
  message: Module still imports helper dropped from package __all__
  severity: Critical
  confidence: certain
  category: Functional Correctness
  source: agent
  fingerprint: benchCrossfileExport01
  tool: agent
  rule_id: agent:bench-crossfile-export-removed
  introduced_by_pr: 'true'
  evidence:
  - ImportError when public surface shrinks without deprecation window
  remediation: Restore export, add compatibility alias, or update importers in same PR.
  autofix: null
  cluster_id: null
run_succeeded: true
trust_tier: trusted
---

Human-labelled corpus case (W9). Cross-file breakage — public export removals must
keep importers consistent.
