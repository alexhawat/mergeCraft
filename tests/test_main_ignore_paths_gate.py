"""Pre-dispatch ``ignore_paths`` gate (#1109): a PR of only ignored files skips the agent.

The gate resolves the run's matcher (recorded for ``checkout_pr``) and, when the pull
request's complete file listing is ignored, records a ``skip`` triage tier so the run
passes with "nothing to review" and approval is left to a human. Any doubt reviews.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.main import SkipAgentReview, _ignore_paths_gate
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.review_policy.ignore_paths import ReviewIgnore


class _Scm:
    def __init__(
        self,
        files: list[str] | None,
        *,
        fail: bool = False,
        renames: dict[str, str] | None = None,
    ) -> None:
        self.files = files
        self.fail = fail
        self.renames = renames or {}

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/files"):
            if self.fail:
                msg = "listing failed"
                raise RuntimeError(msg)
            return [
                {"filename": name, "previous_filename": self.renames.get(name)}
                for name in self.files or []
            ]
        msg = "no base config read expected on an operator-owned run"
        raise AssertionError(msg)


def _ctx(
    files: list[str] | None,
    *,
    fail: bool = False,
    settings: RepoSettings | None = None,
    renames: dict[str, str] | None = None,
) -> Any:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    return SimpleNamespace(
        settings=settings or RepoSettings(),
        tool_state=state,
        tool_context=SimpleNamespace(
            repo=SimpleNamespace(owner="acme", name="demo"),
            scm=_Scm(files, fail=fail, renames=renames),
        ),
        gh_event={"pull_request": {"number": 3, "base": {"sha": "b" * 40}}},
        settings_snapshot_operator_owned=True,
    )


@pytest.fixture(autouse=True)
def _pr_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    monkeypatch.delenv("INPUT_IGNORE_PATHS", raising=False)


@pytest.mark.asyncio
async def test_every_file_ignored_skips_with_nothing_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INPUT_IGNORE_PATHS", "host/evals/**/*.jsonl\nCHANGELOG.md")
    ctx = _ctx(["CHANGELOG.md", "host/evals/a/b.jsonl", "uv.lock"])

    out = await _ignore_paths_gate(ctx)

    assert isinstance(out, SkipAgentReview)
    assert out.reason.startswith("nothing to review")
    assert ctx.tool_state.triage.tier == "skip"
    assert ctx.tool_state.triage.recognizer == "ignorePaths"
    assert ctx.tool_state.ignored_review_paths == [
        "CHANGELOG.md",
        "host/evals/a/b.jsonl",
        "uv.lock",
    ]


@pytest.mark.asyncio
async def test_mixed_pr_runs_the_review_with_the_matcher_recorded() -> None:
    ctx = _ctx(["CHANGELOG.md", "src/app.py"])

    assert await _ignore_paths_gate(ctx) is None

    assert isinstance(ctx.tool_state.review_ignore, ReviewIgnore)
    assert ctx.tool_state.review_ignore.is_ignored("CHANGELOG.md")
    assert ctx.tool_state.triage is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("files", "fail"), [([], False), (None, True)])
async def test_an_empty_or_failed_listing_reviews(files: list[str] | None, *, fail: bool) -> None:
    ctx = _ctx(files, fail=fail)
    assert await _ignore_paths_gate(ctx) is None
    assert ctx.tool_state.triage is None


@pytest.mark.asyncio
async def test_defaults_off_and_no_globs_never_skips() -> None:
    settings = RepoSettings.model_validate({"review": {"ignorePathDefaults": False}})
    ctx = _ctx(["CHANGELOG.md"], settings=settings)
    assert await _ignore_paths_gate(ctx) is None
    assert ctx.tool_state.review_ignore.active is False


@pytest.mark.asyncio
async def test_comment_driven_runs_never_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    ctx = _ctx(["CHANGELOG.md"])
    assert await _ignore_paths_gate(ctx) is None
    assert isinstance(ctx.tool_state.review_ignore, ReviewIgnore)


@pytest.mark.asyncio
async def test_renaming_a_source_file_into_an_ignored_name_is_not_all_ignored() -> None:
    ctx = _ctx(["CHANGELOG.md"], renames={"CHANGELOG.md": "src/auth.py"})
    assert await _ignore_paths_gate(ctx) is None
    assert ctx.tool_state.triage is None


@pytest.mark.asyncio
async def test_renaming_between_ignored_names_is_still_all_ignored() -> None:
    ctx = _ctx(["docs/CHANGELOG.md"], renames={"docs/CHANGELOG.md": "CHANGELOG.md"})
    out = await _ignore_paths_gate(ctx)
    assert isinstance(out, SkipAgentReview)


# A pull request may edit ``.mergecraft/config.yaml`` in the same change that it wants
# left unreviewed. The ``mergecraft review`` gate passes an all-ignored pull request
# without a review, so the ignore decision must come from base (operator) configuration:
# a broad glob the pull request adds to its own config never takes its other files out
# of review.
_BROAD_HEAD_CONFIG = "review:\n  ignorePaths:\n    - '**'\n"
_HEAD_SHA = "h" * 40
_BASE_SHA = "b" * 40


class _RefScm(_Scm):
    """Serves ``.mergecraft/config.yaml`` per ref: plain at base, broad at head."""

    def __init__(self, files: list[str]) -> None:
        super().__init__(files)
        self.config_refs: list[str] = []

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/contents/.mergecraft/config.yaml"):
            ref = str((kwargs.get("params") or {}).get("ref"))
            self.config_refs.append(ref)
            text = _BROAD_HEAD_CONFIG if ref == _HEAD_SHA else "review: {}\n"
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(text.encode()).decode(),
            }
        return await super().get(path, **kwargs)


def _config_edit_ctx(*, operator_owned: bool, settings: RepoSettings | None = None) -> Any:
    files = [".mergecraft/config.yaml", "src/app.py", "CHANGELOG.md"]
    ctx = _ctx(files, settings=settings)
    ctx.tool_context.scm = _RefScm(files)
    ctx.gh_event = {
        "pull_request": {"number": 3, "base": {"sha": _BASE_SHA}, "head": {"sha": _HEAD_SHA}}
    }
    ctx.settings_snapshot_operator_owned = operator_owned
    return ctx


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_name", "operator_owned"),
    [("pull_request_target", True), ("pull_request", False)],
    ids=["pull_request_target-base-snapshot", "pull_request-base-contents"],
)
async def test_a_broad_ignore_glob_added_by_the_pr_does_not_make_it_all_ignored(
    monkeypatch: pytest.MonkeyPatch, event_name: str, *, operator_owned: bool
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    ctx = _config_edit_ctx(operator_owned=operator_owned)

    assert await _ignore_paths_gate(ctx) is None

    assert ctx.tool_state.triage is None
    assert _HEAD_SHA not in ctx.tool_context.scm.config_refs, "head config is never read"
    if not operator_owned:
        assert ctx.tool_context.scm.config_refs == [_BASE_SHA]
    assert ctx.tool_state.review_ignore.is_ignored("src/app.py") is False


@pytest.mark.asyncio
async def test_a_broad_glob_in_base_config_is_the_operators_choice() -> None:
    """The same glob in the base snapshot is trusted: that is how an operator opts out."""
    base = RepoSettings.model_validate({"review": {"ignorePaths": ["**"]}})
    ctx = _config_edit_ctx(operator_owned=True, settings=base)

    out = await _ignore_paths_gate(ctx)

    assert isinstance(out, SkipAgentReview)
    assert ctx.tool_state.triage.recognizer == "ignorePaths"
