"""``ToolContext`` states one trust default, and it is the restrictive one.

``ToolContext`` is ``@dataclass(slots=True, init=False)``: its field defaults
are metadata and construction always runs the hand-written ``__init__``. Both
used to say ``"trusted"``. Unknown trust now means ``untrusted`` in both
places, and ``authority_trust`` keeps deriving from ``trust_tier``.

This is the one suite that constructs a ``ToolContext`` **without** a tier —
on purpose, to pin what the default is. Every other test states its tier.

The constructors that relied on the default are decided, not listed: the
``publish_deterministic_record`` fallback (no event to derive trust from) is
``untrusted``; the local ``acme/demo`` contexts of ``mergecraft agents`` and
the pipeline executor pass ``trusted`` explicitly, so their behaviour does not
change.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import TYPE_CHECKING, Any, cast

import pytest
from tests.support.tool_context import make_tool_context

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_GREEN_AFTER_RESTRICTIVE_DEFAULT = pytest.mark.xfail(
    reason="green after VP4.2: ToolContext defaults trust_tier to untrusted",
    strict=False,
)
_GREEN_AFTER_FALLBACK_TIER = pytest.mark.xfail(
    reason="green after VP4.3: the deterministic-record fallback context is untrusted",
    strict=False,
)


def _bare(tmp_path: Path, **kwargs: Any) -> ToolContext:
    """A ``ToolContext`` with no trust argument unless the caller passes one."""
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=GitHubClient(token=""),
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        tmpdir=str(tmp_path),
        **kwargs,
    )


@_GREEN_AFTER_RESTRICTIVE_DEFAULT
def test_a_bare_context_is_untrusted_on_both_axes(tmp_path: Path) -> None:
    ctx = _bare(tmp_path)
    assert ctx.trust_tier == "untrusted"
    assert ctx.authority_trust == "untrusted"


@_GREEN_AFTER_RESTRICTIVE_DEFAULT
def test_dataclass_metadata_states_the_same_default(tmp_path: Path) -> None:
    """The field metadata and ``__init__`` agree: one default, restrictive."""
    del tmp_path
    fields = {field.name: field for field in dataclasses.fields(ToolContext)}
    init_params = inspect.signature(ToolContext.__init__).parameters

    assert fields["trust_tier"].default == "untrusted"
    assert fields["authority_trust"].default == "untrusted"
    assert init_params["trust_tier"].default == "untrusted"
    # ``authority_trust`` derives from ``trust_tier`` when not passed.
    assert init_params["authority_trust"].default is None


@pytest.mark.parametrize("tier", ["trusted", "untrusted"])
def test_an_explicit_tier_is_honoured_and_authority_follows_it(tmp_path: Path, tier: str) -> None:
    """Green guard: callers that state a tier get exactly that tier on both axes."""
    ctx = _bare(tmp_path, trust_tier=tier)
    assert ctx.trust_tier == tier
    assert ctx.authority_trust == tier


def test_an_explicit_authority_is_kept_apart_from_execution_trust(tmp_path: Path) -> None:
    """Green guard: trusted execution with untrusted authority stays split."""
    ctx = make_tool_context(tmp_path, trust_tier="trusted", authority_trust="untrusted")
    assert ctx.trust_tier == "trusted"
    assert ctx.authority_trust == "untrusted"


def test_the_test_helper_requires_a_tier() -> None:
    """``make_tool_context`` has no trust default: every caller states one."""
    param = inspect.signature(make_tool_context).parameters["trust_tier"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_mergecraft_agents_local_context_stays_trusted(tmp_path: Path) -> None:
    """Green guard: the operator's own ``mergecraft agents`` context keeps its tier."""
    from mergecraft.cli import agents_cmd

    ctx = agents_cmd._tool_ctx(tmp_path)
    assert ctx.trust_tier == "trusted"
    assert ctx.authority_trust == "trusted"


def test_pipeline_executor_local_context_stays_trusted(tmp_path: Path) -> None:
    """Green guard: the local pipeline executor context keeps its tier."""
    from mergecraft.orchestrator import executor

    ctx = executor._tool_ctx(tmp_path)
    assert ctx.trust_tier == "trusted"
    assert ctx.authority_trust == "trusted"


class _Stop(Exception):
    """Raised by the render stub once it has captured the record's inputs."""


@_GREEN_AFTER_FALLBACK_TIER
async def test_deterministic_record_fallback_context_is_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no tool context, the record is rendered for an ``untrusted`` run.

    The fallback has no GitHub event to derive trust from, so it must not
    claim the permissive tier on the published record.
    """
    import mergecraft.findings.ledger as ledger_mod
    import mergecraft.main as main_mod

    captured: dict[str, Any] = {}

    async def _no_history(_ctx: Any) -> Any:
        return None

    def _render(**kwargs: Any) -> str:
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr(ledger_mod, "hydrate_finding_ledger_from_progress_comment", _no_history)
    monkeypatch.setattr(ledger_mod, "render_deterministic_review_block", _render)

    with pytest.raises(_Stop):
        await main_mod.publish_deterministic_record(
            pull_number=7,
            packet=cast("Any", object()),
            tmpdir=str(tmp_path),
        )

    assert captured["trust_tier"] == "untrusted"
