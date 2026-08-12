"""Built-in mode: Fix.

This module exists as a one-mode-per-file split of the legacy
``src/mergecraft/modes.py`` monolith (#145). The prompt text is the
identical body the monolith carried on ``pre-0.0.1`` HEAD — byte-for-byte,
no rewording, no "while I'm here" prompt edits. Any prompt improvement is
a separate PR against this versioned baseline.

Exports:
    NAME: Mode name (``"Fix"``).
    DESCRIPTION: Short description used by ``select_mode``.
    TEMPLATE: The raw template body — ``${...}`` markers are expanded
        by ``compute_modes`` at render time.
"""

from __future__ import annotations

NAME: str = "Fix"
DESCRIPTION: str = (
    "Fix CI failures; debug failing tests or builds; investigate and resolve check suite failures"
)

# Triple-quoted single-quote string preserves the body verbatim. The original
# template is a Python single-quoted string whose escape sequences (\\n,
# \\, etc.) we keep as-is. ``TEMPLATE`` is consumed by ``compute_modes``
# exactly as ``_MODE_DEFS[i][2]`` was in the monolith.
TEMPLATE: str = '### Checklist\n\n1. **task list**: create your task list for this run as your first action.\n\n2. Checkout the PR branch via `${t("checkout_pr")}`.\n\n3. Fetch check suite logs via `${t("get_check_suite_logs")}`.\n\n4. **CRITICAL**: verify the failure was INTRODUCED BY THIS PR before fixing. If unrelated, abort and report.\n\n5. Diagnose and fix:\n   - read the workflow file, reproduce locally with the EXACT same commands CI runs\n   - fix the issue using your native file and shell tools\n   - verify the fix by re-running the exact CI command\n   - review the diff before committing — verify only the fix is present, no debug artifacts, no unrelated changes. the fix should be clean enough that a senior engineer would approve without hesitation.\n   - ${commitStep}\n\n6. Finalize:\n   - ${finalizeStep} (same push/prepush guidance as Build mode in *SYSTEM*)\n   - call `${t("report_progress")}` with the diagnosis and fix summary (or the exact push error if push failed)'
