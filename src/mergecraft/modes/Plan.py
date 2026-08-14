"""Built-in mode: Plan.

This module exists as a one-mode-per-file split of the legacy
``src/mergecraft/modes.py`` monolith (#145). The prompt text is the
identical body the monolith carried on ``pre-0.0.1`` HEAD — byte-for-byte,
no rewording, no "while I'm here" prompt edits. Any prompt improvement is
a separate PR against this versioned baseline.

Exports:
    NAME: Mode name (``"Plan"``).
    DESCRIPTION: Short description used by ``select_mode``.
    TEMPLATE: The raw template body — ``${...}`` markers are expanded
        by ``compute_modes`` at render time.
"""

from __future__ import annotations

NAME: str = "Plan"
DESCRIPTION: str = "Create plans, break down tasks, outline steps, analyze requirements, understand scope of work, or provide task breakdowns"

# Triple-quoted single-quote string preserves the body verbatim. The original
# template is a Python single-quoted string whose escape sequences (\\n,
# \\, etc.) we keep as-is. ``TEMPLATE`` is consumed by ``compute_modes``
# exactly as ``_MODE_DEFS[i][2]`` was in the monolith.
TEMPLATE: str = '### Checklist\n\n1. **task list**: create your task list for this run as your first action.\n\n2. Analyze the task and gather context:\n   - read AGENTS.md and relevant codebase files\n   - understand the architecture and constraints\n\n3. Produce a structured, actionable plan with clear milestones.\n\n4. Call `${t("report_progress")}` with the plan body. Do NOT set `target_plan_comment` — that flag is exclusively for revising an existing plan, and `${t("select_mode")}` will route you to a separate PlanEdit checklist when a prior plan comment exists for this issue.'
