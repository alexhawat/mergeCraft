---
id: pr-250-memory-feedback
title: "PR #250 memory feedback — three review rounds"
category: multi_round_convergence
submitted_at: 2026-08-22T20:00:00Z
run_id: pr-250
pr_number: 250
failure_mode: multi_round_miss
expected_finding: "see rounds[].findings"
expected_decision: neutral
replay_command: "mergecraft eval convergence"
provenance:
  run_id: pr-250
  pr_number: 250
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: 2026-08-22T20:00:00Z
rounds:
  - round_index: 1
    diff_text: |
      diff --git a/src/mergecraft/utils/learnings.py b/src/mergecraft/utils/learnings.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/utils/learnings.py
      +++ b/src/mergecraft/utils/learnings.py
      @@ -740,6 +740,12 @@ def load_weighted_active_memories():
           return []
      +def apply_repo_memory_to_findings(findings):
      +    return findings
      diff --git a/src/mergecraft/cli/memory.py b/src/mergecraft/cli/memory.py
      index 3333333..4444444 100644
      --- a/src/mergecraft/cli/memory.py
      +++ b/src/mergecraft/cli/memory.py
      @@ -115,6 +115,10 @@ def import_memory_bundle(path):
           pass
      +def forget(token):
      +    pass
    findings:
      - fingerprint: b7f9c1baadbf4344d16beb36
        path: src/mergecraft/utils/learnings.py
        start_line: 744
        end_line: 744
        body: apply_repo_memory_to_findings has no callers in src
        first_appeared_round: 1
      - fingerprint: 5ab77564dfeba315ae57f109
        path: src/mergecraft/cli/memory.py
        start_line: 120
        end_line: 120
        body: memory forget silently no-ops on legacy layout
        first_appeared_round: 1
    ledger:
      - fingerprint: b7f9c1baadbf4344d16beb36
        state: deferred
      - fingerprint: 5ab77564dfeba315ae57f109
        state: open
    generated_fingerprints:
      - b7f9c1baadbf4344d16beb36
      - 5ab77564dfeba315ae57f109
  - round_index: 2
    diff_text: |
      diff --git a/src/mergecraft/utils/learnings.py b/src/mergecraft/utils/learnings.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/utils/learnings.py
      +++ b/src/mergecraft/utils/learnings.py
      @@ -740,6 +740,12 @@ def load_weighted_active_memories():
           return []
      +def apply_repo_memory_to_findings(findings):
      +    return findings
      diff --git a/src/mergecraft/cli/memory.py b/src/mergecraft/cli/memory.py
      index 3333333..4444444 100644
      --- a/src/mergecraft/cli/memory.py
      +++ b/src/mergecraft/cli/memory.py
      @@ -115,6 +115,10 @@ def import_memory_bundle(path):
           pass
      +def forget(token):
      +    pass
      @@ -585,6 +589,12 @@ def export_memory_bundle(path):
           pass
      +def import_memory_bundle(path):
      +    pass
    findings:
      - fingerprint: b7f9c1baadbf4344d16beb36
        path: src/mergecraft/utils/learnings.py
        start_line: 744
        end_line: 744
        body: apply_repo_memory_to_findings has no callers in src
        first_appeared_round: 1
      - fingerprint: 5ab77564dfeba315ae57f109
        path: src/mergecraft/cli/memory.py
        start_line: 120
        end_line: 120
        body: memory forget silently no-ops on legacy layout
        first_appeared_round: 1
      - fingerprint: e37d5a8be7fa38715647f548
        path: src/mergecraft/cli/memory.py
        start_line: 591
        end_line: 591
        body: import_memory_bundle wipes legacy learnings on import
        first_appeared_round: 2
      - fingerprint: c9e635fbc425e010b41fbfe2
        path: src/mergecraft/utils/learnings.py
        start_line: 760
        end_line: 760
        body: apply_repo_memory_to_findings lacks trust-tier gate on fork paths
        first_appeared_round: 2
    ledger:
      - fingerprint: b7f9c1baadbf4344d16beb36
        state: open
      - fingerprint: 5ab77564dfeba315ae57f109
        state: open
      - fingerprint: e37d5a8be7fa38715647f548
        state: open
      - fingerprint: c9e635fbc425e010b41fbfe2
        state: deferred
    generated_fingerprints:
      - b7f9c1baadbf4344d16beb36
      - 5ab77564dfeba315ae57f109
      - e37d5a8be7fa38715647f548
      - c9e635fbc425e010b41fbfe2
  - round_index: 3
    diff_text: |
      diff --git a/src/mergecraft/findings/agent_adapter.py b/src/mergecraft/findings/agent_adapter.py
      index 5555555..6666666 100644
      --- a/src/mergecraft/findings/agent_adapter.py
      +++ b/src/mergecraft/findings/agent_adapter.py
      @@ -118,6 +118,12 @@ def normalize_agent_findings_via_pipeline(drafts):
           return drafts
    findings:
      - fingerprint: c9e635fbc425e010b41fbfe2
        path: src/mergecraft/utils/learnings.py
        start_line: 760
        end_line: 760
        body: apply_repo_memory_to_findings lacks trust-tier gate on fork paths
        first_appeared_round: 2
      - fingerprint: 4025b50883ddde0c496616cc
        path: src/mergecraft/findings/agent_adapter.py
        start_line: 121
        end_line: 121
        body: normalize_agent_findings maps refined indices onto pre-suppression drafts
        first_appeared_round: 3
    ledger:
      - fingerprint: c9e635fbc425e010b41fbfe2
        state: open
      - fingerprint: 4025b50883ddde0c496616cc
        state: open
    generated_fingerprints:
      - c9e635fbc425e010b41fbfe2
      - 4025b50883ddde0c496616cc
---

# pr-250-memory-feedback

Multi-round convergence fixture sourced from mergeCraft PR #250 (memory feedback
capture). Round 1 deferred the dead-wiring finding; round 2 surfaced it and
caught import/trust-tier gaps; round 3 caught the agent-adapter index mapping
bug after the trust-tier fix landed.
