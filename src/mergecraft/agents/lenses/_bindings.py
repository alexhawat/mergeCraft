"""Project lens definitions into registry bindings (AP5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.lenses._definitions import LENS_DEFINITIONS
from mergecraft.agents.registry import AgentBinding, AgentRole

if TYPE_CHECKING:
    from mergecraft.agents.lenses._base import LensDefinition
    from mergecraft.config.settings import RepoSettings


def lens_binding(
    lens: LensDefinition,
    *,
    settings: RepoSettings,
    model_chain: tuple[str, ...] | None = None,
) -> AgentBinding:
    """Project a ``LensDefinition`` into a registry ``AgentBinding``."""
    from mergecraft.agents.registry import _default_model_chain

    chain = model_chain or tuple(_default_model_chain(settings, role=AgentRole.reviewer))
    return AgentBinding(
        agent_id=f"lens-{lens.lens_id}",
        role=AgentRole.reviewer,
        lens=lens.lens_id,
        model_chain=chain,
        prompt_id=f"mergecraft.lens.{lens.lens_id}",
        prompt_version="1.0.0",
        tool_classes=lens.tool_classes,
        budget=8,
        timeout_s=600,
        triggers=lens.triggers,
    )


def bundled_lens_bindings(*, settings: RepoSettings) -> dict[str, AgentBinding]:
    """Registry rows for every bundled lens."""
    return {
        f"lens-{lens_id}": lens_binding(defn, settings=settings)
        for lens_id, defn in LENS_DEFINITIONS.items()
    }
