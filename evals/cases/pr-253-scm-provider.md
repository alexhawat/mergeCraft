---
id: pr-253-scm-provider
title: "PR #253 ScmProvider protocol — four review rounds"
category: multi_round_convergence
submitted_at: 2026-08-22T20:05:00Z
run_id: pr-253
pr_number: 253
failure_mode: multi_round_miss
expected_finding: "see rounds[].findings"
expected_decision: neutral
replay_command: "mergecraft eval convergence"
provenance:
  run_id: pr-253
  pr_number: 253
  source_field: eval_bank
  author_login: alexhawat
  author_association: OWNER
  trust_tier: trusted
  timestamp: 2026-08-22T20:05:00Z
rounds:
  - round_index: 1
    diff_text: |
      diff --git a/src/mergecraft/scm/github.py b/src/mergecraft/scm/github.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/scm/github.py
      +++ b/src/mergecraft/scm/github.py
      @@ -232,6 +232,14 @@ class GitHubScmAdapter:
           pass
      +    def get_issue_events(self, owner, repo, number):
      +        return []
      diff --git a/src/mergecraft/main.py b/src/mergecraft/main.py
      index 3333333..4444444 100644
      --- a/src/mergecraft/main.py
      +++ b/src/mergecraft/main.py
      @@ -98,6 +98,10 @@ def _lazy_import():
           pass
      +    mod = "GitHub" + "Client"
    findings:
      - fingerprint: adb01ec4fa14e0392d835c69
        path: src/mergecraft/scm/github.py
        start_line: 237
        end_line: 237
        body: MCP-alias protocol ops diverge from the tools they name
        first_appeared_round: 1
      - fingerprint: abc23125e40c21dbf02a5659
        path: src/mergecraft/main.py
        start_line: 102
        end_line: 102
        body: GitHub Client string obfuscation hides imports from scanners
        first_appeared_round: 1
    ledger:
      - fingerprint: adb01ec4fa14e0392d835c69
        state: deferred
      - fingerprint: abc23125e40c21dbf02a5659
        state: open
    generated_fingerprints:
      - adb01ec4fa14e0392d835c69
      - abc23125e40c21dbf02a5659
  - round_index: 2
    diff_text: |
      diff --git a/src/mergecraft/scm/github.py b/src/mergecraft/scm/github.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/scm/github.py
      +++ b/src/mergecraft/scm/github.py
      @@ -232,6 +232,14 @@ class GitHubScmAdapter:
           pass
      diff --git a/src/mergecraft/main.py b/src/mergecraft/main.py
      index 3333333..4444444 100644
      --- a/src/mergecraft/main.py
      +++ b/src/mergecraft/main.py
      @@ -98,6 +98,10 @@ def _lazy_import():
           pass
      diff --git a/src/mergecraft/mcp/context.py b/src/mergecraft/mcp/context.py
      index 5555555..6666666 100644
      --- a/src/mergecraft/mcp/context.py
      +++ b/src/mergecraft/mcp/context.py
      @@ -84,6 +84,10 @@ class ToolContext:
           self.scm = scm
      +    self.github = github
    findings:
      - fingerprint: adb01ec4fa14e0392d835c69
        path: src/mergecraft/scm/github.py
        start_line: 237
        end_line: 237
        body: MCP-alias protocol ops diverge from the tools they name
        first_appeared_round: 1
      - fingerprint: a2cf24a1499bf8c88e53ff08
        path: src/mergecraft/mcp/context.py
        start_line: 88
        end_line: 88
        body: ctx.github still reachable in unscanned core modules
        first_appeared_round: 2
    ledger:
      - fingerprint: adb01ec4fa14e0392d835c69
        state: open
      - fingerprint: a2cf24a1499bf8c88e53ff08
        state: open
    generated_fingerprints:
      - adb01ec4fa14e0392d835c69
      - a2cf24a1499bf8c88e53ff08
  - round_index: 3
    diff_text: |
      diff --git a/src/mergecraft/mcp/context.py b/src/mergecraft/mcp/context.py
      index 5555555..6666666 100644
      --- a/src/mergecraft/mcp/context.py
      +++ b/src/mergecraft/mcp/context.py
      @@ -84,6 +84,10 @@ class ToolContext:
           self.scm = scm
    findings:
      - fingerprint: a2cf24a1499bf8c88e53ff08
        path: src/mergecraft/mcp/context.py
        start_line: 88
        end_line: 88
        body: ctx.github still reachable in unscanned core modules
        first_appeared_round: 2
    ledger:
      - fingerprint: a2cf24a1499bf8c88e53ff08
        state: resolved-by-change
    generated_fingerprints:
      - a2cf24a1499bf8c88e53ff08
  - round_index: 4
    diff_text: |
      diff --git a/src/mergecraft/scm/github.py b/src/mergecraft/scm/github.py
      index 1111111..2222222 100644
      --- a/src/mergecraft/scm/github.py
      +++ b/src/mergecraft/scm/github.py
      @@ -232,6 +232,14 @@ class GitHubScmAdapter:
           pass
    findings: []
    ledger: []
    generated_fingerprints: []
---

# pr-253-scm-provider

Multi-round convergence fixture sourced from mergeCraft PR #253 (ScmProvider
protocol and adapters). Seven mergecraft review rounds on the real PR; this
case compresses the finding arc into four scored rounds with MCP-alias
divergence deferred in round 1, ctx.github leakage caught in round 2, and
clean approval in round 4.
