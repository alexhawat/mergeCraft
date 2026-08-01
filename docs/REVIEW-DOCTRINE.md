# Review doctrine

Reasoning extracted from pullfrog-py history (`review_checks.py`, `review_taxonomy.py`,
`mcp/static_checks.py`, `REVIEW-CHECKS.md`) before the mergeCraft snapshot. W2 and W5
build on these decisions — they are not recoverable from code alone.

## Mechanical gates vs findings

**`unavailable` is not `failed`.** A gate whose executable is missing (no `make`, no
linter on PATH) says nothing about the diff. Reporting it as a failure invents a finding.
Only a real non-zero exit from an executable gate is evidence. The Action image ships
`git`, `gh`, `jq`, `node`, and `npm` — not `make` — so every Makefile-discovered target
lands as `unavailable` there unless the repo declares explicit `staticChecks` with binaries
that exist in the image.

## Makefile discovery, not tool inference

**`DISCOVERABLE_TARGETS` discovers Makefile targets, not tools.** The tuple
`("lint", "format-check", "typecheck", "ci-static")` is offered in order when no
`staticChecks` are declared. Nothing is inferred from file extensions; no interpreter or
linter is substituted. The repo's own gate is the only gate.

## Never substitute a toolchain version

When the repo has a tool, mergeCraft runs **the repo's copy** at **the repo's config and
version**. A reviewer carrying its own interpreter manufactures findings: `except A, B:`
is a `SyntaxError` under Python 3.13 and legal under 3.14 (PEP 758), which this project
requires. The module docstring, tool description, and mode prompt all encode this rule.

## Finding fingerprints

**`finding_fingerprint()` = `sha256(path + "\n" + casefolded whitespace-collapsed body)[:24]`.**
Whitespace and case are normalized so re-wrapping a comment does not change the hash, letting
a later run recognize a finding it already raised. The marker is stamped server-side in
`mcp/review.py`. **Cost:** paraphrases and minor rewordings produce new fingerprints; the
tradeoff favors stable dedup over semantic similarity.

## Output cap

**`MAX_OUTPUT_CHARS = 8_000`** caps combined stdout+stderr embedded in prompts. Raw tool output
beyond this truncates — a design constraint for W4's move to file-based parsing. Mechanical
gate output is evidence, not the finding itself.

## Subagent deny-list

**`subagent_denied_tool_names()` derives from every MCP tool with `mutates=True`.** If that
list is empty, startup **raises** — refusing to run a review subagent with the mutation gate
effectively disabled. The verification agent (W7) inherits the same guard.

## Shell permission and static checks

**`run_static_checks` is withheld under `shell: disabled`.** Gates execute commands the repo
config names; on a pull request those are commands the PR author controls. Offline
`mergecraft diff-review` keeps the tool because config and tree belong to the operator.

## Provenance

Harvested from pullfrog-py `origin/main` commits `bff76e7` (feat/review-triage-and-mechanical-gates)
and `31441ce` (fix/static-check-availability-and-shell-gate), PR #20.
