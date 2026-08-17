"""Lens menu rendering without importing the agents package surface (AP5)."""

from __future__ import annotations

from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS, PROMPT_LENS_IDS


def render_lens_menu_block() -> str:
    """Render starter-menu bullets for orchestrator prompts."""
    lines = [
        "   starter menu for identifying hypotheses (combine, omit, or invent your own; "
        "do not dispatch a bare menu label without a falsifiable question):",
    ]
    for lens_id in sorted(PROMPT_LENS_IDS, key=lambda item: LENS_DEFINITIONS[item].title):
        lens = LENS_DEFINITIONS[lens_id]
        lines.append(f"   - **{lens.title}** — {lens.rubric}")
    lines.append(
        "   - **subsystem lenses** (invent as the PR demands) — auth, billing, payments, "
        "schema migration, webhooks, secrets, RBAC, multi-tenant isolation, cron/scheduling, etc."
    )
    return "\n".join(lines)
