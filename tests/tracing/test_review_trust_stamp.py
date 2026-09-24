"""TB6 — the recorded review tier matches the run's resolved tier.

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB6).

The Action entry point binds its :class:`ReviewContext` before credentials
resolve. For a comment-on-PR run the pre-binding event carries no head, so
``derive_trust_tier`` floors to ``untrusted`` — even when
``_resolve_credentials`` then binds a same-repo PR and the run executes
``trusted``. Recording that floor as ``review.trust_tier`` would read the
opposite of ``tool_state.trust_tier``.

The two facts are recorded under two names:

* ``review.raw_event_trust_floor`` — the fail-closed tier the raw pre-binding
  event implies (kept for trace consumers that want the floor);
* ``review.trust_tier`` / ``mergecraft.trust_tier`` — the tier the run actually
  used, stamped by ``_stamp_review_trust_tier`` once materialize has resolved
  it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

# A same-repo PR under a maintainer's ``@mergecraft review`` comment: the
# ``issue_comment`` event carries ``issue.pull_request`` but no head, so the
# pre-binding tier floors to ``untrusted`` until ``get_pull`` binds it.
_COMMENT_ON_PR_EVENT: dict[str, Any] = {
    "action": "created",
    "issue": {
        "number": 42,
        "title": "Add the widget",
        "pull_request": {"url": "https://api.github.com/repos/acme/demo/pulls/42"},
    },
    "comment": {"author_association": "OWNER", "body": "@mergecraft review"},
    "repository": {"full_name": "acme/demo", "default_branch": "main"},
}


def _set_comment_on_pr_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Point the process at a comment-on-PR event file (the raw, unbound shape)."""
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_COMMENT_ON_PR_EVENT), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/demo")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.delenv("MERGECRAFT_TRUST_TIER", raising=False)


def test_action_context_records_the_raw_floor_and_no_run_tier(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """TB6 — the entry-point context records the raw floor, never an unbound tier."""
    _set_comment_on_pr_env(monkeypatch, tmp_path)

    from mergecraft.main import _action_review_context

    review_ctx = _action_review_context()

    assert review_ctx.raw_event_trust_floor == "untrusted"
    assert review_ctx.trust_tier == "", "the pre-binding context must not claim a run tier"
    attrs = review_ctx.attrs()
    assert attrs["review.raw_event_trust_floor"] == "untrusted"
    assert attrs["mergecraft.raw_event_trust_floor"] == "untrusted"
    assert "review.trust_tier" not in attrs
    assert "mergecraft.trust_tier" not in attrs


def test_bound_same_repo_run_stamps_the_resolved_tier_and_keeps_the_floor(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """TB6 — a bound same-repo run records ``trusted`` as the tier and ``untrusted`` as the floor.

    The run's resolved tier (``tool_state.trust_tier``) is stamped onto the bound
    context; the pre-binding floor stays available under its own name. Removing
    the stamp leaves ``review.trust_tier`` absent, so this test fails.
    """
    _set_comment_on_pr_env(monkeypatch, tmp_path)

    from mergecraft.main import RunContext, _action_review_context, _stamp_review_trust_tier
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.tracing.review_context import bind_review_context, current_review_context

    review_ctx = _action_review_context()
    run_ctx = RunContext()
    run_ctx.tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    # ``_resolve_credentials`` bound the same-repo PR and resolved the tier.
    run_ctx.tool_state.trust_tier = "trusted"

    with bind_review_context(review_ctx):
        _stamp_review_trust_tier(run_ctx)
        stamped = current_review_context()

    assert stamped is not None
    attrs = stamped.attrs()
    assert run_ctx.tool_state.trust_tier == "trusted"
    assert attrs["review.trust_tier"] == "trusted"
    assert attrs["review.trust_tier"] == run_ctx.tool_state.trust_tier
    assert attrs["mergecraft.trust_tier"] == "trusted"
    # The raw floor is untouched and clearly distinct from the run tier.
    assert attrs["review.raw_event_trust_floor"] == "untrusted"
    assert attrs["mergecraft.raw_event_trust_floor"] == "untrusted"
    assert attrs["review.trust_tier"] != attrs["review.raw_event_trust_floor"]
    assert set(attrs) >= {
        "review.trust_tier",
        "mergecraft.trust_tier",
        "review.raw_event_trust_floor",
        "mergecraft.raw_event_trust_floor",
    }


def test_stamp_is_a_noop_without_a_bound_context(monkeypatch: MonkeyPatch) -> None:
    """TB6 — stamping with no bound context is total and never raises."""
    from mergecraft.tracing.review_context import stamp_review_context

    monkeypatch.delenv("MERGECRAFT_REVIEW_ID", raising=False)

    assert stamp_review_context(trust_tier="trusted") is None
