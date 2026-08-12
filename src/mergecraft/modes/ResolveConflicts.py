"""Built-in mode: ResolveConflicts.

This module exists as a one-mode-per-file split of the legacy
``src/mergecraft/modes.py`` monolith (#145). The prompt text is the
identical body the monolith carried on ``pre-0.0.1`` HEAD — byte-for-byte,
no rewording, no "while I'm here" prompt edits. Any prompt improvement is
a separate PR against this versioned baseline.

Exports:
    NAME: Mode name (``"ResolveConflicts"``).
    DESCRIPTION: Short description used by ``select_mode``.
    TEMPLATE: The raw template body — ``${...}`` markers are expanded
        by ``compute_modes`` at render time.
"""

from __future__ import annotations

NAME: str = "ResolveConflicts"
DESCRIPTION: str = "Resolve merge conflicts in a PR branch against the base branch"

# Triple-quoted single-quote string preserves the body verbatim. The original
# template is a Python single-quoted string whose escape sequences (\\n,
# \\, etc.) we keep as-is. ``TEMPLATE`` is consumed by ``compute_modes``
# exactly as ``_MODE_DEFS[i][2]`` was in the monolith.
TEMPLATE: str = '### Checklist\n\n1. **task list**: create your task list for this run as your first action.\n\n2. **Setup**:\n   - Call `${t("checkout_pr")}` to get the PR branch.\n   - Call `${t("get_pull_request")}` to identify the base branch (e.g., \'main\').\n   - Call `${t("git_fetch")}` to fetch the base branch.\n\n3. **Merge Attempt**:\n   - Run `git merge ${signedCommits ? "--no-commit " : ""}origin/<base_branch>` via shell.\n   - If it succeeds automatically, ${signedCommits ? <<<NEST>>>conclude it via `${t("commit_changes")}` (it turns the pending merge into a signed merge commit on the remote)<<</NEST>>> : <<<NEST>>>confirm a clean working tree, push via `${t("push_branch")}` (same push/prepush guidance as Build mode in *SYSTEM*)<<</NEST>>>}, and call `${t("report_progress")}` with a brief success note or the exact error if it failed — **then stop; do not run steps 4–5.**\n   - If it fails (conflicts), resolve them manually (continue to steps 4–5).\n\n4. **Resolve Conflicts**:\n   - Run `git status` or parse the merge output to find the list of conflicting files.\n   - For each conflicting file: read it, find the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`), understand the code context, and rewrite the file with the correct resolution. Remove all markers.\n   - Verify the file syntax is correct after resolution.\n\n5. **Finalize**:\n   - Run a final verification (build/test) to ensure the resolution works.\n   - ${signedCommits ? <<<NEST>>>`git add .`, then conclude via `${t("commit_changes")}` with message "resolve merge conflicts"<<</NEST>>> : <<<NEST>>>`git add . && git commit -m "resolve merge conflicts"`<<</NEST>>>}\n   - ${finalizeStep} (same push/prepush guidance as Build mode in *SYSTEM*)\n   - Call `${t("report_progress")}` with a summary of what was resolved (or the exact push error if push failed)'
