---
id: pr-216-eval-gate-matrix
title: "PR #216 eval gate matrix — four review rounds"
category: multi_round_convergence
submitted_at: 2026-08-22T20:10:00Z
run_id: pr-216
pr_number: 216
failure_mode: multi_round_miss
expected_finding: "see rounds[].findings"
expected_decision: neutral
replay_command: "mergecraft eval convergence"
provenance:
  run_id: pr-216
  pr_number: 216
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: 2026-08-22T20:10:00Z
rounds:
  - round_index: 1
    diff_text: |
      diff --git a/src/mergecraft/evals/benchmark.py b/src/mergecraft/evals/benchmark.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/evals/benchmark.py
      +++ b/src/mergecraft/evals/benchmark.py
      @@ -328,6 +328,14 @@ def _classify_gate_outcome(case):
           pass
    findings:
      - fingerprint: 51df3ff413a7faeaa8cb5578
        path: src/mergecraft/evals/benchmark.py
        start_line: 332
        end_line: 332
        body: untrusted-tier neutral counted as buggy_unsafe_approval
        first_appeared_round: 1
    ledger:
      - fingerprint: 51df3ff413a7faeaa8cb5578
        state: deferred
    generated_fingerprints:
      - 51df3ff413a7faeaa8cb5578
  - round_index: 2
    diff_text: |
      diff --git a/src/mergecraft/evals/benchmark.py b/src/mergecraft/evals/benchmark.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/evals/benchmark.py
      +++ b/src/mergecraft/evals/benchmark.py
      @@ -328,6 +328,14 @@ def _classify_gate_outcome(case):
           pass
      diff --git a/src/mergecraft/evals/live_run.py b/src/mergecraft/evals/live_run.py
      index 3333333..4444444 100644
      --- a/src/mergecraft/evals/live_run.py
      +++ b/src/mergecraft/evals/live_run.py
      @@ -206,6 +206,12 @@ def run_live_detection(case):
           pass
    findings:
      - fingerprint: 51df3ff413a7faeaa8cb5578
        path: src/mergecraft/evals/benchmark.py
        start_line: 332
        end_line: 332
        body: untrusted-tier neutral counted as buggy_unsafe_approval
        first_appeared_round: 1
      - fingerprint: d2c49b4df86d9c0bf48ca6d8
        path: src/mergecraft/evals/live_run.py
        start_line: 210
        end_line: 210
        body: failed live reviews scored as zero-finding pass
        first_appeared_round: 2
    ledger:
      - fingerprint: 51df3ff413a7faeaa8cb5578
        state: open
      - fingerprint: d2c49b4df86d9c0bf48ca6d8
        state: deferred
    generated_fingerprints:
      - 51df3ff413a7faeaa8cb5578
      - d2c49b4df86d9c0bf48ca6d8
  - round_index: 3
    diff_text: |
      diff --git a/src/mergecraft/evals/live_run.py b/src/mergecraft/evals/live_run.py
      index 3333333..4444444 100644
      --- a/src/mergecraft/evals/live_run.py
      +++ b/src/mergecraft/evals/live_run.py
      @@ -206,6 +206,12 @@ def run_live_detection(case):
           pass
      diff --git a/src/mergecraft/evals/benchmark.py b/src/mergecraft/evals/benchmark.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/evals/benchmark.py
      +++ b/src/mergecraft/evals/benchmark.py
      @@ -567,6 +567,14 @@ class VersionPins(BaseModel):
           pass
    findings:
      - fingerprint: d2c49b4df86d9c0bf48ca6d8
        path: src/mergecraft/evals/live_run.py
        start_line: 210
        end_line: 210
        body: failed live reviews scored as zero-finding pass
        first_appeared_round: 2
      - fingerprint: f06191a0373eddde54a0fdca
        path: src/mergecraft/evals/benchmark.py
        start_line: 571
        end_line: 571
        body: pre-1.2.0 reviewing_model shape silently parses
        first_appeared_round: 3
    ledger:
      - fingerprint: d2c49b4df86d9c0bf48ca6d8
        state: open
      - fingerprint: f06191a0373eddde54a0fdca
        state: open
    generated_fingerprints:
      - d2c49b4df86d9c0bf48ca6d8
      - f06191a0373eddde54a0fdca
  - round_index: 4
    diff_text: |
      diff --git a/evals/results/latest.json b/evals/results/latest.json
      index 5555555..6666666 100644
      --- a/evals/results/latest.json
      +++ b/evals/results/latest.json
      @@ -1,3 +1,3 @@
      -{"unsafe_approval_rate": 0.03}
      +{"unsafe_approval_rate": 0.0}
    findings: []
    ledger: []
    generated_fingerprints: []
---

# pr-216-eval-gate-matrix

Multi-round convergence fixture sourced from mergeCraft PR #216 (B2–B4 eval
gate metrics). Four mergecraft review rounds on the real PR; this case tracks
the untrusted-tier gate misclassification (round 1), failed-live-run scoring
(round 2–3), and VersionPins schema enforcement (round 3).
