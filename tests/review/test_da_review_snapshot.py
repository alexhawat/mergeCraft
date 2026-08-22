"""#380 one engine over one ``ReviewSnapshot``.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Authoring wave: **W2**. Implementation: **W6** (xfail markers removed after W6).

CLI (``review``), Action (``mergecraft.main`` / ``gha``), and SCM
(``conforming_review_request``) enter one engine over one snapshot. Hidden
``diff-review`` must remain.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.review.engine import ReviewEngine
from mergecraft.review.snapshot import ReviewSnapshot
from mergecraft.scm.webhooks import ConformingReviewRequest, conforming_review_request

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_review_is_the_documented_command() -> None:
    """Happy: ``review`` is listed; ``diff-review`` stays hidden (W6 must keep the alias)."""
    result = runner.invoke(app, ["--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "review" in help_text.casefold()
    assert "diff-review" not in help_text


def test_hidden_diff_review_alias_remains_invocable() -> None:
    """Edge: hidden ``diff-review`` still serves ``--help`` (do not delete the alias)."""
    result = runner.invoke(app, ["diff-review", "--help"], env=_DUMB_ENV)
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    names = {cmd.name for cmd in app.registered_commands if cmd.name}
    assert "diff-review" in names
    hidden = [cmd for cmd in app.registered_commands if cmd.name == "diff-review"]
    assert hidden
    assert hidden[0].hidden is True


def test_review_snapshot_type_exists() -> None:
    """Unit: ``ReviewSnapshot`` is a public type CLI / Action / SCM can share."""
    assert inspect.isclass(ReviewSnapshot)
    assert ReviewSnapshot.__name__ == "ReviewSnapshot"


def test_shared_engine_accepts_review_snapshot() -> None:
    """Unit: ``ReviewEngine`` is constructed with a ``ReviewSnapshot``."""
    params = inspect.signature(ReviewEngine.__init__).parameters
    assert "snapshot" in params
    annotation = str(params["snapshot"].annotation)
    assert "ReviewSnapshot" in annotation


def test_cli_review_path_builds_a_review_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: CLI review constructs a ``ReviewSnapshot`` on the engine."""
    seen: list[ReviewSnapshot] = []
    orig = ReviewEngine.__init__

    def counted(self: ReviewEngine, *args: object, **kwargs: object) -> None:
        orig(self, *args, **kwargs)
        seen.append(self.snapshot)

    monkeypatch.setattr(ReviewEngine, "__init__", counted)
    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        lambda **_kwargs: None,
    )
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert seen
    assert all(isinstance(snapshot, ReviewSnapshot) for snapshot in seen)
    assert seen[0].entry == "cli"


@pytest.mark.asyncio
async def test_action_path_builds_a_review_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Integration: Action ``main`` constructs a ``ReviewSnapshot``."""
    from tests.support.run_main_harness import run_main_for_test

    seen: list[ReviewSnapshot] = []
    orig = ReviewEngine.__init__

    def counted(self: ReviewEngine, *args: object, **kwargs: object) -> None:
        orig(self, *args, **kwargs)
        seen.append(self.snapshot)

    monkeypatch.setattr(ReviewEngine, "__init__", counted)
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
    )
    assert rec.raised is None, rec.raised
    assert seen
    assert isinstance(seen[0], ReviewSnapshot)
    assert seen[0].entry == "action"


def test_scm_conforming_request_builds_or_feeds_a_review_snapshot() -> None:
    """Integration: SCM webhook review requests enter the same snapshot type."""
    request = conforming_review_request("github", event="pull_request", body={})
    assert isinstance(request, ConformingReviewRequest)
    assert isinstance(request.snapshot, ReviewSnapshot)
    assert request.snapshot.entry == "scm"
