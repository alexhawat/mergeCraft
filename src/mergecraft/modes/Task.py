"""Built-in mode: Task.

This module exists as a one-mode-per-file split of the legacy
``src/mergecraft/modes.py`` monolith (#145). The prompt text is the
identical body the monolith carried on ``pre-0.0.1`` HEAD — byte-for-byte,
no rewording, no "while I'm here" prompt edits. Any prompt improvement is
a separate PR against this versioned baseline.

Exports:
    NAME: Mode name (``"Task"``).
    DESCRIPTION: Short description used by ``select_mode``.
    TEMPLATE: The raw template body — ``${...}`` markers are expanded
        by ``compute_modes`` at render time.
"""

from __future__ import annotations

NAME: str = "Task"
DESCRIPTION: str = "General-purpose tasks that don't fit other modes: answering questions, adding comments, labeling, running ad-hoc commands, or any direct request"

# Triple-quoted single-quote string preserves the body verbatim. The original
# template is a Python single-quoted string whose escape sequences (\\n,
# \\, etc.) we keep as-is. ``TEMPLATE`` is consumed by ``compute_modes``
# exactly as ``_MODE_DEFS[i][2]`` was in the monolith.
TEMPLATE: str = '### Checklist\n\n1. **task list**: create your task list for this run as your first action.\n\n2. Analyze the task. For simple operations (labeling, answering questions, running a single command), handle directly — but your answer only reaches the user through `${t("report_progress")}` (step 4); raw assistant text is discarded. If a standalone comment on the current issue/PR is the task\'s sole requested deliverable, create that comment directly and skip `${t("report_progress")}`.\n\n3. For substantial work — code changes across multiple files, multi-step investigations:\n   - plan your approach before starting\n   - use native file and shell tools for local operations\n   - use ${mergecraftMcpName} MCP tools for GitHub/git operations\n   - if code changes are needed: review your own diff before committing — verify only intended changes are present, no debug artifacts remain, and the changes are clean enough that a senior engineer would approve without hesitation\n\n4. Finalize:\n   - if code changes were made, get them onto a pull request (new or existing) using ${signedCommits ? <<<NEST>>>`${t("commit_changes")}`<<</NEST>>> : <<<NEST>>>`${t("push_branch")}`<<</NEST>>>} and `${t("create_pull_request")}` as needed. `git status` must be clean before you finish (see *SYSTEM* Git rules if this fails).\n   - call `${t("report_progress")}` once with results — include exact tool errors if push or PR creation failed. skip this only when a standalone comment on the current target was the task\'s sole requested deliverable\n   - if the task involved labeling or other GitHub operations, perform those directly'
