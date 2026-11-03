"""``checkout_pr`` keeps files ignored by config out of the reviewer's diff (#1109).

The diff on disk is what the reviewer reads and what the changed-line coverage gate
accounts against, so an ignored file must be absent from both: it is out of scope, not
unread. The tool result names the ignored files and the review body lists them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout_coverage import _mark_read, _patched_file
from tests.mcp.test_checkout_degraded_diff import (
    _checkout,
    _ctx_for,
    _fail_merge_base_diff,
    _git,
    _StubGitHub,
)

from mergecraft.config.settings import ReviewSettings
from mergecraft.review_policy.ignore_paths import build_review_ignore

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _mixed_pr_repo(tmp_path: Path, *, with_source: bool = True) -> Path:
    """A PR that changes source (unless ``with_source`` is false), a changelog, a lockfile
    and eval data."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "base")
    _git(work, "checkout", "-b", "feature")
    if with_source:
        (work / "feature.py").write_text("changed = 1\n", encoding="utf-8")
    (work / "CHANGELOG.md").write_text("# Changelog\n- CHANGELOG_SECRET\n", encoding="utf-8")
    (work / "uv.lock").write_text("LOCK_CONTENT = 1\n", encoding="utf-8")
    evals = work / "host" / "evals" / "suite"
    evals.mkdir(parents=True)
    (evals / "case.jsonl").write_text('{"EVAL_PAYLOAD": 1}\n', encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "feature")
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone


def _git_diff(repo: Path) -> str:
    return subprocess.run(
        ["git", "diff", "--merge-base", "origin/base", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _ignore(input_value: str | None = "host/evals/**/*.jsonl\nCHANGELOG.md") -> Any:
    return build_review_ignore(input_value=input_value, review=ReviewSettings(), source="test")


@pytest.mark.asyncio
async def test_ignored_files_never_reach_the_reviewer_diff(tmp_path: Path) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _mixed_pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)
    ctx.tool_state.review_ignore = _ignore()

    is_error, payload = await _checkout(ctx)

    assert is_error is False
    assert isinstance(payload, dict)
    diff_text = _read_text(payload["diffPath"])
    assert "feature.py" in diff_text
    for leaked in ("CHANGELOG_SECRET", "LOCK_CONTENT", "EVAL_PAYLOAD"):
        assert leaked not in diff_text
    assert sorted(payload["ignoredPaths"]) == [
        "CHANGELOG.md",
        "host/evals/suite/case.jsonl",
        "uv.lock",
    ]
    assert "not reviewed (ignored by config)" in payload["ignoredPathsNote"]
    assert sorted(ctx.tool_state.ignored_review_paths) == sorted(payload["ignoredPaths"])

    authoritative = ctx.tool_state.coverage.authoritative_diff or ""
    assert "CHANGELOG_SECRET" not in authoritative
    _mark_read(ctx, "feature.py")
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is True, "ignored files are out of scope, not unread"
    assert {row.path for row in section.uncovered}.isdisjoint(set(payload["ignoredPaths"]))


@pytest.mark.asyncio
async def test_without_a_matcher_the_diff_is_unchanged(tmp_path: Path) -> None:
    repo = _mixed_pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)

    _is_error, payload = await _checkout(ctx)

    assert isinstance(payload, dict)
    diff_text = _read_text(payload["diffPath"])
    assert "CHANGELOG_SECRET" in diff_text
    assert "ignoredPaths" not in payload
    assert ctx.tool_state.ignored_review_paths == []


@pytest.mark.asyncio
async def test_files_api_diff_drops_ignored_and_unreviewable_ignored_files(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _mixed_pr_repo(tmp_path)
    files = {
        1: [
            _patched_file("feature.py"),
            _patched_file("CHANGELOG.md"),
            # A huge eval file GitHub sends no patch for: ignored, so not "unreviewable".
            {
                "filename": "host/evals/suite/big.jsonl",
                "additions": 9000,
                "deletions": 0,
                "patch": None,
            },
        ]
    }
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)
    ctx.tool_state.review_ignore = _ignore()

    is_error, payload = await _checkout(ctx)

    assert is_error is False
    assert isinstance(payload, dict)
    assert "unreviewablePaths" not in payload
    assert payload["ignoredPaths"] == ["CHANGELOG.md", "host/evals/suite/big.jsonl"]
    assert ctx.tool_state.coverage.unreviewable_paths == []
    diff_text = _read_text(payload["diffPath"])
    assert "CHANGELOG.md" not in diff_text
    _mark_read(ctx, "feature.py")
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is True


def test_coverage_drops_ignored_hunks_but_never_filters_to_an_empty_scope() -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state
    from mergecraft.mcp.tool_state import init_tool_state

    changelog = (
        "diff --git a/CHANGELOG.md b/CHANGELOG.md\n"
        "--- a/CHANGELOG.md\n"
        "+++ b/CHANGELOG.md\n"
        "@@ -0,0 +1 @@\n"
        "+x\n"
    )
    source = "diff --git a/src/app.py b/src/app.py\n@@ -0,0 +1 @@\n+y\n"
    state = init_tool_state(owner="acme", name="demo", dir=".")
    state.review_ignore = _ignore(None)

    state.coverage.authoritative_diff = source + changelog
    mixed = coverage_section_for_state(state)
    assert mixed is not None
    assert {row.path for row in mixed.uncovered} == {"src/app.py"}

    state.coverage.authoritative_diff = changelog
    state.coverage.unreviewable_paths = ["uv.lock"]
    all_ignored = coverage_section_for_state(state)
    assert all_ignored is not None, "an all-ignored scope must not read as nothing to gate"
    assert all_ignored.complete is False


@pytest.mark.asyncio
async def test_all_ignored_pr_on_a_comment_driven_review_cannot_be_approved(
    tmp_path: Path,
) -> None:
    """MC-d4c038: the pre-dispatch gate skips neither a slash-command review nor a run
    whose file listing failed, so the checkout must not hand the agent an empty scope it
    could approve: a complete diff of only ignored files records the skip tier."""
    from tests.evidence.test_run_packet import _make_ctx

    from mergecraft.evidence.run_packet import build_run_packet

    (tmp_path / "pr").mkdir()
    repo = _mixed_pr_repo(tmp_path / "pr", with_source=False)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path / "pr")
    ctx.tool_state.review_ignore = _ignore()  # resolved by the gate, which did not skip

    is_error, payload = await _checkout(ctx)

    assert is_error is False
    assert isinstance(payload, dict)
    filtered = _read_text(payload["diffPath"])
    assert filtered.strip() == ""
    assert ctx.tool_state.triage is not None
    assert (ctx.tool_state.triage.tier, ctx.tool_state.triage.recognizer) == (
        "skip",
        "ignorePaths",
    )

    # The strongest case: evidence that would otherwise approve (the unfiltered change
    # set, an approving agent, no findings). The skip tier must still hold approval back.
    unfiltered = _git_diff(repo)
    packet_dir = tmp_path / "packet"
    packet_dir.mkdir()
    packet_ctx = _make_ctx(packet_dir, diff_text=unfiltered, findings=[])
    packet_ctx.authority_trust = "trusted"
    premise = build_run_packet(packet_ctx, run_succeeded=True)
    assert premise.decision is not None
    assert premise.decision.verdict == "success", "fixture premise: this evidence approves"

    packet_ctx.tool_state.triage = ctx.tool_state.triage
    packet = build_run_packet(packet_ctx, run_succeeded=True)
    assert packet.decision is not None
    assert packet.decision.verdict != "success"
    assert packet.decision.verdict == "neutral"


@pytest.mark.asyncio
async def test_truncated_listing_of_ignored_files_is_reviewed_unfiltered(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mergecraft.mcp import checkout as checkout_module

    monkeypatch.setattr(checkout_module, "_PULL_FILES_MAX_PAGES", 1)
    page = [_patched_file(f"pkg{i}/yarn.lock") for i in range(100)]
    repo = _mixed_pr_repo(tmp_path)
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages={1: page}), tmp_path)
    ctx.tool_state.review_ignore = _ignore()

    is_error, payload = await _checkout(ctx)

    assert is_error is False
    assert isinstance(payload, dict)
    assert payload["diffTruncated"] is True
    assert "ignoredPaths" not in payload
    assert "pkg0/yarn.lock" in _read_text(payload["diffPath"])
    assert ctx.tool_state.triage is None
    assert ctx.tool_state.ignored_review_paths == []


def test_unreviewable_generated_file_with_its_generator_config_stays_uncovered() -> None:
    """A generated file kept in scope because its generator config changed must still
    count as unread when GitHub sent no patch for it."""
    from mergecraft.evidence.coverage import coverage_section_for_state
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir=".")
    state.review_ignore = _ignore(None)
    state.coverage.authoritative_diff = (
        "diff --git a/openapi-generator.yaml b/openapi-generator.yaml\n"
        "@@ -1 +1 @@\n"
        "-version: 1\n"
        "+version: 2\n"
        "diff --git a/api/generated/client.py b/api/generated/client.py\n"
    )
    state.coverage.unreviewable_paths = ["api/generated/client.py"]

    section = coverage_section_for_state(state)

    assert section is not None
    assert ("api/generated/client.py", "no_inline_patch") in {
        (row.path, row.cause) for row in section.uncovered
    }
    assert section.complete is False


def _generator_then_output_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Commit A (reviewed) changes the generator config; commit B regenerates output."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "base")
    _git(work, "checkout", "-b", "feature")
    (work / "openapi-generator.yaml").write_text("version: 2\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "bump the generator config")
    reviewed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
    generated = work / "api" / "generated"
    generated.mkdir(parents=True)
    (generated / "client.py").write_text("GENERATED_CLIENT = 2\n", encoding="utf-8")
    (work / "CHANGELOG.md").write_text("# Changelog\n- CHANGELOG_SECRET\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "regenerate the client")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone, reviewed, head


@pytest.mark.asyncio
async def test_rereview_keeps_generated_output_when_its_config_changed_in_an_earlier_round(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The incremental range alone lacks the generator config; the PR's change set has it."""
    from tests.mcp import test_checkout as base_checkout

    repo, reviewed_sha, head_sha = _generator_then_output_repo(tmp_path)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    base_checkout._pin_publishers(monkeypatch, frozenset({base_checkout._PUBLISHER_LOGIN}))
    github = base_checkout._StubGitHub(
        head_sha=head_sha,
        reviews=[
            {
                "commit_id": reviewed_sha,
                "body": base_checkout._MERGECRAFT_BODY,
                "user": base_checkout._BOT_USER,
            }
        ],
    )
    ctx = base_checkout._ctx_for(repo, github, tmp_path, mode="IncrementalReview")
    ctx.tool_state.review_ignore = _ignore(None)

    payload = await base_checkout._checkout(ctx)

    assert payload["incrementalDiffStatus"] == "ok"
    incremental = _read_text(payload["incrementalDiffPath"])
    assert "GENERATED_CLIENT" in incremental, "generated output stays in scope"
    assert "CHANGELOG_SECRET" not in incremental, "changelogs are still ignored"
    assert "GENERATED_CLIENT" in _read_text(payload["diffPath"])
    assert "api/generated/client.py" not in payload.get("ignoredPaths", [])
