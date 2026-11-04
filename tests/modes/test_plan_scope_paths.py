"""Plan mode asks the plan body to end with a ``Scope paths:`` block (#1056 part 3).

The declared-scope gate reads a ``Scope paths:`` block from the pull request or
the issues it closes. Plan mode writes those plans, so its checklist gains one
line telling the plan body to end with that block, listing the globs the change
is expected to touch. Nothing else in the template changes.
"""

from __future__ import annotations

from mergecraft.modes import compute_modes


def _scope_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "Scope paths:" in line]


def test_the_plan_template_has_one_scope_paths_checklist_line() -> None:
    from mergecraft.modes import Plan

    lines = _scope_lines(Plan.TEMPLATE)

    assert len(lines) == 1
    line = lines[0].casefold()
    assert "`scope paths:`" in line
    assert "glob" in line
    assert "end" in line


def test_the_rendered_plan_prompt_carries_the_line_for_every_provider() -> None:
    for provider in ("claude", "opencode"):
        plan = next(mode for mode in compute_modes(provider) if mode.name == "Plan")

        assert len(_scope_lines(plan.prompt or "")) == 1, provider


def test_the_scope_line_sits_inside_the_checklist() -> None:
    from mergecraft.modes import Plan

    template = Plan.TEMPLATE

    assert template.index("### Checklist") < template.index("Scope paths:")


def test_plan_is_the_only_mode_that_asks_for_a_scope_block() -> None:
    asking = [mode.name for mode in compute_modes("opencode") if _scope_lines(mode.prompt or "")]

    assert asking == ["Plan"]
