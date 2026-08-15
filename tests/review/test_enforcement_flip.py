"""VP4 enforcement flip — ``gates.terminal_verdict`` defaults to ``enforce``.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP4.1 RED, VP4.2 impl).

Pinned contracts (W0):
    D6 — enforce only after shadow (VP3 landed; this PR flips the default).
    Shadow remains a selectable ``GateMode`` value (escape hatch).
"""

from __future__ import annotations

import pytest

from mergecraft.config.settings import RepoSettings, default_settings

_VP42 = pytest.mark.xfail(
    reason="green after VP4.2: terminal_verdict default is enforce",
    strict=False,
)


@_VP42
def test_enforce_is_default_after_this_pr() -> None:
    """After VP4.2, a repo that omits ``gates.terminal_verdict`` enforces."""
    assert default_settings().gates.terminal_verdict == "enforce"


def test_shadow_can_still_be_selected() -> None:
    """Compatibility pin: operators can still opt back into shadow."""
    settings = RepoSettings.model_validate({"gates": {"terminal_verdict": "shadow"}})
    assert settings.gates.terminal_verdict == "shadow"
