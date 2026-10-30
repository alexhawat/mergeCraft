"""#1078 — only the rung a fallback replaces may suppress its formal review.

The OpenCode Go step is non-terminal when Codex is available, so it receives
``MERGECRAFT_STICKY_ONLY_NEUTRAL``. Codex and Claude are terminal for a neutral
decision (Claude advances only on a retryable failure), so they must not carry
the flag: suppressing their formal review would leave the PR with no review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.ci.support_self_review_cascade import step_by_id

if TYPE_CHECKING:
    from typing import Any

_VARIABLE = "MERGECRAFT_STICKY_ONLY_NEUTRAL"


def _env(step_id: str) -> dict[str, Any]:
    env = step_by_id(step_id).get("env")
    assert isinstance(env, dict), f"{step_id} must declare an env mapping"
    return env


def test_the_opencode_go_rung_is_sticky_only_when_codex_is_available() -> None:
    env = _env("mergecraft_opencode_go")
    assert env.get(_VARIABLE) == "${{ env.HAS_CODEX }}"


def test_terminal_rungs_never_set_the_sticky_only_flag() -> None:
    for step_id in ("mergecraft_codex", "mergecraft_claude"):
        assert _VARIABLE not in _env(step_id), (
            f"{step_id} decides the run when its verdict is neutral; suppressing its "
            "formal review would publish nothing"
        )
