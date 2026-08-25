"""Built-in agent modes — one module per mode, plus a stable package surface.

The pre-``#145`` monolith at ``src/mergecraft/modes.py`` (~84 KB of prompt
text) has been split into :mod:`mergecraft.modes.<Name>` so each mode is
reviewable on its own. This package preserves the public surface the rest
of the codebase already imports:

- :data:`Mode` (the Pydantic model)
- :data:`PR_SUMMARY_FORMAT` (the review body format constant)
- :func:`compute_modes` (the renderer)
- :data:`modes` (the static, UI-facing list)
- :data:`NON_COMMITTING_MODES` (the closed set of non-mutating mode names)
- :func:`_custom_modes` (the helper that projects ``settings.modes`` — see
  ``main.py`` — into ``Mode`` objects; now exported from the package root
  so the existing call sites do not change)

Exports for the prompt-version contract (#145):

- :data:`compute_prompt_version` — the content-hash helper. A mode's
  version is derived from its prompt body, never stored independently;
  an edit cannot silently keep the old version.
- :data:`prompt_version_for` — look up the version for a built-in mode
  name; mirrors the ``VERIFIER_RUBRIC_VERSION`` / ``VERIFIER_JUDGE_VERSION``
  precedent and is emitted into run evidence and trace attrs.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mergecraft.config.settings import ModeDefinition

# Per-mode modules — each carries ``NAME`` / ``DESCRIPTION`` / ``TEMPLATE``.
from mergecraft.modes import (
    AddressReviews,
    Build,
    Fix,
    IncrementalReview,
    Plan,
    ResolveConflicts,
    Review,
    Task,
)
from mergecraft.modes._pr_summary_format import PR_SUMMARY_FORMAT
from mergecraft.types import (
    MERGECRAFT_MCP_NAME,
    RECALL_AGENT_NAME,
    REVIEWER_AGENT_NAME,
    VERIFIER_AGENT_NAME,
    AgentId,
    format_mcp_tool_ref,
)


class Mode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    prompt: str | None = None
    #: Content-hash version of the prompt body (#145). Derived from the
    #: rendered prompt at construction time so a prompt edit cannot
    #: silently keep the old version — see ``compute_prompt_version``.
    version: str = ""


# Write-capable built-ins stay importable as negative fixtures (D12 / #350)
# but are not registered for production review.
WRITE_CAPABLE_MODE_NAMES: Final[frozenset[str]] = frozenset(
    {
        Build.NAME,
        AddressReviews.NAME,
        Fix.NAME,
        ResolveConflicts.NAME,
        Task.NAME,
    }
)
_WRITE_CAPABLE_MODE_NAMES_CF: Final[frozenset[str]] = frozenset(
    name.casefold() for name in WRITE_CAPABLE_MODE_NAMES
)
REVIEWER_SHAPED_MODE_NAMES: Final[frozenset[str]] = frozenset(
    {
        Review.NAME,
        IncrementalReview.NAME,
    }
)

# Production registry is review-only (#350). Write-capable modules remain
# on disk and importable; they are not listed here.
_MODE_DEFS: Final[list[tuple[str, str, str]]] = [
    (Review.NAME, Review.DESCRIPTION, Review.TEMPLATE),
    (IncrementalReview.NAME, IncrementalReview.DESCRIPTION, IncrementalReview.TEMPLATE),
    (Plan.NAME, Plan.DESCRIPTION, Plan.TEMPLATE),
]


def production_mode_names() -> list[str]:
    """Return built-in mode names registered for production review."""
    return [name for name, _, _ in _MODE_DEFS]


def is_write_capable_mode_name(name: str) -> bool:
    """Return True when ``name`` matches a write-capable built-in (case-insensitive)."""
    return name.casefold() in _WRITE_CAPABLE_MODE_NAMES_CF


def refuse_review_only_mutation(selected_mode: str | None, *, action: str) -> None:
    """Raise unless a write-capable mode is selected (default-deny).

    Unset ``selected_mode`` (orchestrator before ``select_mode``) is treated
    as review-only. Production has no write-capable modes registered.

    Args:
        selected_mode: The mode currently selected for the run, if any.
        action: Short description of the refused verb (must name it).
    """
    if selected_mode is not None and is_write_capable_mode_name(selected_mode):
        return
    if selected_mode is None:
        msg = f"review-only: {action} is not allowed until a write-capable mode is selected"
        raise RuntimeError(msg)
    msg = f"review-only: {action} is not allowed in {selected_mode} mode"
    raise RuntimeError(msg)


_T_CALL_RE = re.compile(r"\$\{t\(\"([^\"]+)\"\)\}")
_SIGNED_SIMPLE_RE = re.compile(r'\$\{signedCommits \? "(.*?)" : "(.*?)"\}')
_SIGNED_NEST_RE = re.compile(
    r"\$\{signedCommits \? <<<NEST>>>(.*?)<<</NEST>>> : <<<NEST>>>(.*?)<<</NEST>>>\}",
    re.DOTALL,
)


def compute_prompt_version(body: str) -> str:
    """Return the content-hash version of ``body`` (#145).

    A mode's version is derived from its rendered prompt body so an edit
    cannot silently keep the old version — the helper is the same shape
    as :func:`hashlib`'s hex digest but truncated to a stable, human-
    readable form. ``VERIFIER_RUBRIC_VERSION`` / ``VERIFIER_JUDGE_VERSION``
    follow the same pattern: a pinned literal that bumps on content
    change. Identical bodies yield identical versions; any change yields
    a different one.
    """
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def prompt_version_for(name: str) -> str:
    """Return the prompt version for the built-in mode named ``name``.

    The version is computed from the *rendered* prompt — the body after
    every ``${...}`` marker is expanded — so it is stable across the
    ``signed_commits`` toggle but moves when the prompt text moves.
    Raises :class:`KeyError` if the name does not match a built-in.
    """
    for mode_name, _, template in _MODE_DEFS:
        if mode_name != name:
            continue

        # ``format_mcp_tool_ref`` is agent-dependent; for the version hash
        # use a sentinel agent id so the result is independent of the
        # caller's runtime choice.
        def t(tool_name: str, _agent: AgentId = "opencode") -> str:
            return format_mcp_tool_ref(_agent, tool_name)

        commit_step = 'commit locally via shell (`git add . && git commit -m "..."`)'
        finalize_step = f"confirm a clean working tree, then push via `{t('push_branch')}`"
        rendered = _expand_template(
            template,
            t=t,
            commit_step=commit_step,
            finalize_step=finalize_step,
            signed_commits=False,
        )
        return compute_prompt_version(rendered)
    msg = f"unknown built-in mode: {name!r}"
    raise KeyError(msg)


def _render_lens_menu_block() -> str:
    from mergecraft.agents.lenses._menu import render_lens_menu_block

    return render_lens_menu_block()


def _expand_template(
    template: str,
    *,
    t: Callable[[str], str],
    commit_step: str,
    finalize_step: str,
    signed_commits: bool,
) -> str:
    text = template
    text = text.replace("${REVIEWER_AGENT_NAME}", REVIEWER_AGENT_NAME)
    text = text.replace("${mergecraftMcpName}", MERGECRAFT_MCP_NAME)
    text = text.replace("${commitStep}", commit_step)
    text = text.replace("${finalizeStep}", finalize_step)
    text = text.replace("${PR_SUMMARY_FORMAT}", PR_SUMMARY_FORMAT)
    # PR_SUMMARY_FORMAT embeds ${VERIFIER_AGENT_NAME}; expand after injection.
    text = text.replace("${VERIFIER_AGENT_NAME}", VERIFIER_AGENT_NAME)
    text = text.replace("${RECALL_AGENT_NAME}", RECALL_AGENT_NAME)
    text = text.replace("${LENS_MENU_BLOCK}", _render_lens_menu_block())

    def signed_simple(m: re.Match[str]) -> str:
        return m.group(1) if signed_commits else m.group(2)

    text = _SIGNED_SIMPLE_RE.sub(signed_simple, text)

    def signed_nest(m: re.Match[str]) -> str:
        branch = m.group(1) if signed_commits else m.group(2)
        # Nested branches may contain `${t("tool")}` (optionally backtick-wrapped).
        return _T_CALL_RE.sub(lambda tm: t(tm.group(1)), branch)

    text = _SIGNED_NEST_RE.sub(signed_nest, text)
    return _T_CALL_RE.sub(lambda m: t(m.group(1)), text)


def compute_modes(agent_id: AgentId, signed_commits: bool = False) -> list[Mode]:
    """Return built-in modes with tool refs formatted for ``agent_id``."""

    def t(tool_name: str) -> str:
        return format_mcp_tool_ref(agent_id, tool_name)

    if signed_commits:
        commit_step = (
            f"commit via `{t('commit_changes')}` — it lands a GitHub-signed commit "
            "directly on the remote branch (no push step)"
        )
        finalize_step = (
            f"confirm a clean working tree (`git status`) — your `{t('commit_changes')}` "
            "calls already landed the work on the remote"
        )
    else:
        commit_step = 'commit locally via shell (`git add . && git commit -m "..."`)'
        finalize_step = f"confirm a clean working tree, then push via `{t('push_branch')}`"

    result: list[Mode] = []
    for name, description, template in _MODE_DEFS:
        prompt = _expand_template(
            template,
            t=t,
            commit_step=commit_step,
            finalize_step=finalize_step,
            signed_commits=signed_commits,
        )
        result.append(
            Mode(
                name=name,
                description=description,
                prompt=prompt,
                version=compute_prompt_version(prompt),
            )
        )
    return result


def _custom_modes(defs: Sequence[ModeDefinition]) -> list[Mode]:
    """Project ``settings.modes`` (a list of :class:`ModeDefinition`) into Mode objects.

    Moved from ``src/mergecraft/main.py`` so the modes package owns the
    built-in ↔ custom merge contract. ``main.py`` now imports this helper
    from here. Custom modes have empty ``version`` — they are not pinned
    by content hash because the source-of-truth is the consumer's config,
    not a built-in file in this repo.

    The argument is typed ``Sequence[ModeDefinition]`` so the merge contract
    is total at static-analysis time; callers that pass ``None`` or a
    non-iterable will fail loudly at the boundary instead of raising an
    ``AttributeError`` mid-iteration. ``ModeDefinition`` is imported only
    under :data:`TYPE_CHECKING` to avoid a runtime import cycle through
    :mod:`mergecraft.config.settings`.
    """
    out: list[Mode] = []
    for d in defs:
        if is_write_capable_mode_name(d.name) or is_write_capable_mode_name(d.id):
            continue
        prompt = d.prompt or None
        version = compute_prompt_version(prompt) if prompt else ""
        out.append(Mode(name=d.name, description=d.description, prompt=prompt, version=version))
    return out


# Static export for UI display — uses opencode format as the readable default.
modes: list[Mode] = compute_modes("opencode")

NON_COMMITTING_MODES: frozenset[str] = frozenset(
    {
        "Review",
        "IncrementalReview",
        "Plan",
    }
)


__all__ = [
    "NON_COMMITTING_MODES",
    "PR_SUMMARY_FORMAT",
    "REVIEWER_SHAPED_MODE_NAMES",
    "WRITE_CAPABLE_MODE_NAMES",
    "_MODE_DEFS",
    "Mode",
    "_custom_modes",
    "compute_modes",
    "compute_prompt_version",
    "is_write_capable_mode_name",
    "modes",
    "production_mode_names",
    "prompt_version_for",
    "refuse_review_only_mutation",
]
