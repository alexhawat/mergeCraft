"""C2 / C16 — production prompts may name only registered MCP tools (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decisions:

* **PD-D1** — delete the classifier-routing paragraph; the prompt names only
  what exists. ``classify_change``, ``route_lenses``, ``selected_lens_ids`` and
  ``load_lens_catalog`` must not appear in any rendered production prompt.
* **PD-D3** — every registered tool name in a production prompt (Review,
  IncrementalReview, Plan and ``PR_SUMMARY_FORMAT``) goes through
  ``${t("...")}``; a bare-backticked registered name is a contract breach.

The registered-name set is derived from the real registry
(``build_orchestrator_tools``) with every optional tool enabled — never
hardcoded. These assertions fail until PD2; do not xfail: RED is the point.
"""

from __future__ import annotations

import re
import tempfile
from typing import TYPE_CHECKING, cast

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_orchestrator_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import (
    PR_SUMMARY_FORMAT,
    IncrementalReview,
    Plan,
    Review,
    compute_modes,
    production_mode_names,
)
from mergecraft.types import XrepoConfig
from tests.support.run_main_harness import FakeGitHubClient

if TYPE_CHECKING:
    from mergecraft.utils.github import GitHubClient

_T_CALL_RE = re.compile(r'\$\{t\("([^"]+)"\)\}')
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")

# PD-D1 — names the reviewing model cannot call or read.
_FORBIDDEN_NAMES: tuple[str, ...] = (
    "classify_change",
    "route_lenses",
    "selected_lens_ids",
    "load_lens_catalog",
)

_MODE_MODULES = (Review, IncrementalReview, Plan)
_TEMPLATE_BY_NAME: dict[str, str] = {module.NAME: module.TEMPLATE for module in _MODE_MODULES}


def _registered_tool_names() -> set[str]:
    """Return every tool ``build_orchestrator_tools`` registers, all options on.

    ``signed_commits`` (commit_changes), static checks, analyzers, cross-repo
    and shell tools are all enabled so the set is the union a production run
    could ever present to the model.
    """
    with tempfile.TemporaryDirectory() as tmp:
        state = init_tool_state(owner="acme", name="demo", dir=tmp)
        ctx = ToolContext(
            agent_id="claude",
            repo=RepoIdentity(owner="acme", name="demo"),
            payload=ResolvedPayload(
                event=PayloadEvent(trigger="pull_request"),
                shell="restricted",
                push="disabled",
            ),
            github=cast("GitHubClient", FakeGitHubClient(token="")),
            modes=compute_modes("claude"),
            tool_state=state,
            tmpdir=tmp,
            signed_commits=True,
            static_checks_enabled=True,
            analyzers_settings_enabled=True,
            analyzers_mode="full",
            xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
        )
        return {
            spec.name for spec in build_orchestrator_tools(ctx, output_schema={"type": "object"})
        }


def _rendered_prompt(mode_name: str) -> str:
    for mode in compute_modes("claude"):
        if mode.name == mode_name:
            assert mode.prompt is not None, f"mode {mode_name!r} rendered no prompt"
            return mode.prompt
    msg = f"mode {mode_name!r} missing from compute_modes"
    raise AssertionError(msg)


def test_every_production_mode_has_a_template() -> None:
    assert set(_TEMPLATE_BY_NAME) == set(production_mode_names())


def test_registered_tool_set_is_not_empty() -> None:
    names = _registered_tool_names()
    assert "submit_review_verdict" in names
    assert "verify_agent_findings" in names


@pytest.mark.parametrize("mode_name", production_mode_names())
def test_source_tool_refs_are_registered(mode_name: str) -> None:
    """Every ``${t("x")}`` in the source template must name a real tool (C16)."""
    registered = _registered_tool_names()
    referenced = set(_T_CALL_RE.findall(_TEMPLATE_BY_NAME[mode_name]))
    unregistered = sorted(referenced - registered)
    assert not unregistered, (
        f"{mode_name} interpolates tool names no registry entry provides: {unregistered}"
    )


@pytest.mark.parametrize("mode_name", production_mode_names())
def test_no_registered_tool_name_is_bare_backticked(mode_name: str) -> None:
    """No registered tool name may appear bare-backticked in the rendered prompt.

    PD-D3: a name used as prose is still interpolated — one rule.
    """
    registered = _registered_tool_names()
    spans = set(_BACKTICK_RE.findall(_rendered_prompt(mode_name)))
    bare = sorted(spans & registered)
    assert not bare, (
        f"{mode_name} renders registered tool names without ${{t(...)}} interpolation: {bare}"
    )


@pytest.mark.parametrize("mode_name", production_mode_names())
def test_forbidden_names_absent_from_rendered_prompt(mode_name: str) -> None:
    """PD-D1 — the classifier/router names must not survive in any prompt."""
    prompt = _rendered_prompt(mode_name)
    present = sorted(name for name in _FORBIDDEN_NAMES if name in prompt)
    assert not present, f"{mode_name} still names non-existent tools: {present}"


def test_pr_summary_format_tool_refs_are_registered() -> None:
    registered = _registered_tool_names()
    referenced = set(_T_CALL_RE.findall(PR_SUMMARY_FORMAT))
    unregistered = sorted(referenced - registered)
    assert not unregistered, (
        f"PR_SUMMARY_FORMAT interpolates unregistered tool names: {unregistered}"
    )


def test_pr_summary_format_has_no_bare_registered_tool_names() -> None:
    """PD-D3 explicitly covers ``PR_SUMMARY_FORMAT`` (spliced into both prompts)."""
    registered = _registered_tool_names()
    spans = set(_BACKTICK_RE.findall(PR_SUMMARY_FORMAT))
    bare = sorted(spans & registered)
    assert not bare, f"PR_SUMMARY_FORMAT renders registered tool names bare: {bare}"
