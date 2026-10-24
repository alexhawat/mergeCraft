"""Review prompt v5 — reading discipline and the ``${TIME_BUDGET}`` marker.

Self-review of PR #1045 (36 files, 25-minute limit) timed out with no verdict:
the agent read function bodies through ~40 ``git grep -A 40..70`` calls, retried
failed lookups with variants, ran ``run_analyzers`` at minute 21, and was still
exploring when killed. Review and IncrementalReview now state the agent's
deadline with stop-exploring / submit checkpoints, and tell it how to read code
without flooding its context. These tests pin the marker's render and the
deadline threading in ``main.py``.
"""

from __future__ import annotations

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.main import RunContext, _agent_timeout_ms, _render_run_modes
from mergecraft.modes import IncrementalReview, Review, compute_modes
from mergecraft.types import AgentId

_REVIEW_MODES = ("Review", "IncrementalReview")
_AGENTS: tuple[AgentId, ...] = ("claude", "codex", "opencode")
_TEMPLATES = (Review.TEMPLATE, IncrementalReview.TEMPLATE)
_TEMPLATE_IDS = (Review.NAME, IncrementalReview.NAME)


def _prompt(name: str, *, time_budget_minutes: int | None = None) -> str:
    for mode in compute_modes("opencode", time_budget_minutes=time_budget_minutes):
        if mode.name == name:
            assert mode.prompt is not None
            return mode.prompt
    msg = f"mode {name!r} missing"
    raise AssertionError(msg)


@pytest.mark.parametrize("name", _REVIEW_MODES)
def test_time_budget_renders_minutes_and_checkpoints_with_a_deadline(name: str) -> None:
    prompt = _prompt(name, time_budget_minutes=25)
    assert "you have about 25 minutes for this run" in prompt
    assert "By about minute 15 (~60% of it), stop exploring" in prompt
    assert "By about minute 20 (~80%), submit the verdict with what you have" in prompt
    assert "not as a reason to keep exploring" in prompt


@pytest.mark.parametrize("name", _REVIEW_MODES)
def test_time_budget_renders_a_neutral_line_without_a_deadline(name: str) -> None:
    prompt = _prompt(name)
    assert "this run has no fixed time limit" in prompt
    assert "minutes for this run" not in prompt


def test_time_budget_checkpoints_stay_positive_for_tiny_deadlines() -> None:
    prompt = _prompt("Review", time_budget_minutes=0)
    assert "you have about 1 minutes for this run. By about minute 1 " in prompt


@pytest.mark.parametrize("agent_id", _AGENTS)
@pytest.mark.parametrize("time_budget_minutes", [None, 1, 25, 60])
def test_time_budget_never_leaves_a_raw_marker(
    agent_id: AgentId, time_budget_minutes: int | None
) -> None:
    for signed in (False, True):
        for mode in compute_modes(
            agent_id, signed, inline_budget=8, time_budget_minutes=time_budget_minutes
        ):
            prompt = mode.prompt or ""
            assert "${TIME_BUDGET}" not in prompt, mode.name
            assert "${" not in prompt, mode.name


def test_deadline_changes_the_recorded_prompt_version() -> None:
    """The version hashes the rendered prompt, so a stated deadline is attributable."""
    without = next(m for m in compute_modes("opencode") if m.name == "Review")
    with_deadline = next(
        m for m in compute_modes("opencode", time_budget_minutes=25) if m.name == "Review"
    )
    assert without.version != with_deadline.version


@pytest.mark.parametrize("template", _TEMPLATES, ids=_TEMPLATE_IDS)
def test_triage_carries_the_reading_rule_not_unbounded_context(template: str) -> None:
    assert template.count("${TIME_BUDGET}") == 1
    assert "pull as much context" not in template
    assert "plain `grep -n` (no `-A` / `-B` / `-C` context flags)" in template
    assert "limit of about 60 lines" in template
    assert "read it whole once rather than in several snippets" in template
    assert "do not repeat a call whose result is already in your context" in template
    assert "fix the arguments once; do not retry variants" in template
    assert "highest risk first" in template
    assert "you do not need to grep the callers of every changed symbol" in template
    assert "**you are the synthesizer" in template


@pytest.mark.parametrize("template", _TEMPLATES, ids=_TEMPLATE_IDS)
def test_diff_fallback_runs_git_diff_once(template: str) -> None:
    assert "run `git diff <base>...HEAD` once for the whole PR" in template
    assert "never once per file or path group" in template


def test_review_keeps_the_never_reconstruct_rule() -> None:
    assert "Never reconstruct the scope with git." in Review.TEMPLATE


@pytest.mark.parametrize("template", _TEMPLATES, ids=_TEMPLATE_IDS)
def test_analyzers_are_the_first_calls_after_checkout(template: str) -> None:
    assert 'Right after `${t("checkout_pr")}` returns, before you read any source file' in (
        template
    )
    assert "In the same turn, " not in template


@pytest.mark.parametrize("template", _TEMPLATES, ids=_TEMPLATE_IDS)
def test_specialist_threshold_no_longer_denies_any_budget(template: str) -> None:
    assert "hard-budget threshold" not in template
    assert "Nor is the number of specialists tied to a file-count" in template


def test_agent_timeout_deducts_setup_elapsed() -> None:
    assert _agent_timeout_ms(RunContext(timeout_ms=None)) is None
    assert _agent_timeout_ms(RunContext(timeout_ms=1_500_000)) == 1_500_000
    ctx = RunContext(timeout_ms=1_500_000, setup_elapsed_s=90.0)
    assert _agent_timeout_ms(ctx) == 1_410_000
    assert _agent_timeout_ms(RunContext(timeout_ms=1_000, setup_elapsed_s=5.0)) == 1


def test_run_modes_state_the_agent_deadline_net_of_setup() -> None:
    ctx = RunContext(settings=RepoSettings(), timeout_ms=25 * 60_000, setup_elapsed_s=90.0)
    review = next(m for m in _render_run_modes(ctx, "opencode") if m.name == "Review")
    assert review.prompt is not None
    assert "you have about 23 minutes for this run" in review.prompt


def test_run_modes_without_a_timeout_render_the_neutral_line() -> None:
    ctx = RunContext(settings=RepoSettings(), timeout_ms=None)
    review = next(m for m in _render_run_modes(ctx, "claude") if m.name == "Review")
    assert review.prompt is not None
    assert "this run has no fixed time limit" in review.prompt
