"""Bundled themed lens catalog (AP5).

Twenty registry-backed lenses (thirteen starter-menu + seven backlog) plus
orchestrator-invented subsystem lenses synthesized at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.lens_triggers import LensTriggers
from mergecraft.agents.lenses._base import LensDefinition
from mergecraft.agents.lenses._definitions import (
    BACKLOG_LENS_IDS,
    LENS_DEFINITIONS,
    PROMPT_LENS_IDS,
)
from mergecraft.agents.lenses._menu import render_lens_menu_block
from mergecraft.mcp.shared import REVIEWER_ALLOWED_TOOL_CLASSES

if TYPE_CHECKING:
    from mergecraft.agents.registry import AgentBinding
    from mergecraft.config.settings import RepoSettings

_DEFAULT_SUBSYSTEM_EVIDENCE: tuple[str, ...] = ("diff_hunk", "domain_context")


class LensCatalog:
    """Resolved view over bundled lens definitions."""

    __slots__ = ("_definitions",)

    def __init__(self, definitions: dict[str, LensDefinition]) -> None:
        self._definitions = definitions

    @property
    def prompt_lens_ids(self) -> frozenset[str]:
        return PROMPT_LENS_IDS

    @property
    def backlog_lens_ids(self) -> frozenset[str]:
        return BACKLOG_LENS_IDS

    @property
    def all_lens_ids(self) -> frozenset[str]:
        return frozenset(self._definitions)


def load_lens_catalog() -> LensCatalog:
    """Return the bundled lens catalog."""
    return LensCatalog(dict(LENS_DEFINITIONS))


def get_lens(lens_id: str) -> LensDefinition:
    """Return one bundled lens; raise ``KeyError`` when unknown."""
    try:
        return LENS_DEFINITIONS[lens_id]
    except KeyError as exc:
        msg = f"unknown lens id: {lens_id!r}"
        raise KeyError(msg) from exc


def build_subsystem_lens(lens_id: str) -> LensDefinition:
    """Synthesize an orchestrator-invented subsystem lens (not in the catalog)."""
    slug = lens_id.strip().lower().replace(" ", "-")
    title = slug.replace("-", " ")
    return LensDefinition(
        lens_id=slug,
        title=title,
        rubric=(
            f"domain-scoped review frame for the {title} subsystem — apply domain-specific "
            "failure modes, invariants, and rollout risks the generic themed lenses miss"
        ),
        triggers=LensTriggers(categories=("auth_security_payment",), min_risk_band="medium"),
        required_evidence=_DEFAULT_SUBSYSTEM_EVIDENCE,
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    )


def resolve_lens_prompt(lens_id: str) -> str:
    """Return dispatch rubric text for one lens id (bundled or subsystem)."""
    try:
        return get_lens(lens_id).rubric
    except KeyError:
        return build_subsystem_lens(lens_id).rubric


def bundled_lens_bindings(*, settings: RepoSettings) -> dict[str, AgentBinding]:
    from mergecraft.agents.lenses._bindings import bundled_lens_bindings as _bundled

    return _bundled(settings=settings)


__all__ = [
    "BACKLOG_LENS_IDS",
    "PROMPT_LENS_IDS",
    "LensCatalog",
    "LensDefinition",
    "build_subsystem_lens",
    "bundled_lens_bindings",
    "get_lens",
    "load_lens_catalog",
    "render_lens_menu_block",
    "resolve_lens_prompt",
]
