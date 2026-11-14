"""Saved git output is complete and inside the reviewer's read boundary (#1474)."""

from __future__ import annotations

import asyncio
import fnmatch
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.mcp.test_git_tool import _ctx
from tests.support.policy_fixtures import commit_all, init_git_repo

from mergecraft.agents.opencode import build_security_config
from mergecraft.agents.shared import AgentRunContext
from mergecraft.mcp.git import git_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.utils.git_setup import is_run_owned_directory

if TYPE_CHECKING:
    import pytest

_LINES = [f"line {n:03d} = {n * 7}" for n in range(1, 501)]


def _last_match(rules: dict[str, str], requested: str) -> str | None:
    """Resolve ``requested`` the way OpenCode does: the last matching rule wins."""
    verdict = None
    for pattern, action in rules.items():
        if fnmatch.fnmatchcase(requested, pattern.replace("**", "*")):
            verdict = action
    return verdict


def _production_split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A checkout and an operator-chosen temp dir this run did not create."""
    repo = init_git_repo(tmp_path / "repo")
    (repo / "big.txt").write_text("\n".join(_LINES) + "\n")
    commit_all(repo, "add big file")
    temp = tmp_path / "shared-tmp"
    temp.mkdir()
    (temp / "other-run-secret.txt").write_text("not for this agent\n")
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(temp))
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    return repo, temp


def _permissions(repo: Path, temp: Path) -> dict[str, Any]:
    ctx = AgentRunContext(
        payload={"shell": "restricted", "push": "restricted"},
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(temp),
        subagent_denied_tools=(),
        instructions="review",
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        mcp_auth_token="token",
    )
    return json.loads(build_security_config(ctx, "anthropic/claude-sonnet"))["permission"]


def _tool(repo: Path, temp: Path) -> Any:
    ctx = _ctx(repo)
    ctx.tmpdir = str(temp)
    return git_tool(ctx)


def _git(repo: Path, temp: Path, command: str, args: list[str]) -> dict[str, Any]:
    result = asyncio.run(_tool(repo, temp).execute({"command": command, "args": args}))
    assert not result.is_error, result.content
    return json.loads(result.content[0]["text"])


def _assert_readable(permissions: dict[str, Any], path: Path) -> None:
    """Both gates OpenCode applies to a native read outside the project root."""
    assert _last_match(permissions["external_directory"], f"{path.parent.as_posix()}/**") == (
        "allow"
    )
    assert _last_match(permissions["read"], path.as_posix()) == "allow"


def test_every_line_of_a_historical_file_is_readable_under_the_review_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, temp = _production_split(tmp_path, monkeypatch)
    assert not is_run_owned_directory(str(temp))
    permissions = _permissions(repo, temp)

    shown = _git(repo, temp, "show", ["HEAD:big.txt"])

    exported = Path(shown["outputPath"])
    _assert_readable(permissions, exported)
    assert exported.read_text(encoding="utf-8").splitlines() == _LINES
    assert shown["totalLines"] == 500
    assert shown["truncated"] is True
    # The preview is bounded, says so, and names the readable file.
    preview = shown["output"].splitlines()
    assert preview[:3] == _LINES[:3]
    assert len(preview) < 500
    assert "of 500 shown" in preview[-1]
    assert str(exported) in preview[-1]


def test_a_short_historical_file_is_returned_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, temp = _production_split(tmp_path, monkeypatch)
    (repo / "small.txt").write_text("\n".join(_LINES[:60]) + "\n")
    commit_all(repo, "add small file")

    shown = _git(repo, temp, "show", ["HEAD:small.txt"])

    assert shown["output"].splitlines() == _LINES[:60]
    assert shown["truncated"] is False


def test_a_single_overlong_line_is_reported_as_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-line blob past the character bound (minified JSON) must say it was cut."""
    repo, temp = _production_split(tmp_path, monkeypatch)
    minified = "{" + ",".join(f'"k{n}":{n}' for n in range(4000)) + "}"
    (repo / "bundle.min.json").write_text(minified)
    commit_all(repo, "add minified file")

    shown = _git(repo, temp, "show", ["HEAD:bundle.min.json"])

    exported = Path(shown["outputPath"])
    assert exported.read_text(encoding="utf-8") == minified
    assert shown["totalLines"] == 1
    assert shown["truncated"] is True
    head, marker = shown["output"].split("\n")
    assert len(head) == 12_000
    assert minified.startswith(head)
    assert "long lines cut at 12000 characters" in marker
    assert str(exported) in marker


def test_the_preview_stops_at_the_character_bound_before_the_line_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, temp = _production_split(tmp_path, monkeypatch)
    wide = [f"{n:03d} " + "y" * 496 for n in range(100)]
    (repo / "wide-lines.txt").write_text("\n".join(wide) + "\n")
    commit_all(repo, "add wide-line file")

    shown = _git(repo, temp, "show", ["HEAD:wide-lines.txt"])

    *head, marker = shown["output"].splitlines()
    assert head == wide[: len(head)]
    assert 0 < len(head) < 100
    assert sum(len(line) + 1 for line in head) <= 12_000
    assert shown["truncated"] is True
    assert f"lines 1-{len(head)} of 100 shown" in marker
    assert "long lines cut" not in marker
    assert Path(shown["outputPath"]).read_text(encoding="utf-8").splitlines() == wide


def test_a_large_git_output_export_is_complete_and_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, temp = _production_split(tmp_path, monkeypatch)
    wide = [f"{n:05d} " + "x" * 60 for n in range(1500)]
    (repo / "wide.txt").write_text("\n".join(wide) + "\n")
    commit_all(repo, "add wide file")
    permissions = _permissions(repo, temp)

    grepped = _git(repo, temp, "grep", ["-h", "x", "--", "wide.txt"])

    exported = Path(grepped["outputPath"])
    _assert_readable(permissions, exported)
    saved = exported.read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1500
    assert saved[-1].endswith(wide[-1])
    assert grepped["truncated"] is True
    assert grepped["totalLines"] == 1500
    assert str(exported) in grepped["output"]


def test_the_export_grant_opens_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared temp dir, ``.git/config`` and unrelated paths stay denied."""
    repo, temp = _production_split(tmp_path, monkeypatch)
    permissions = _permissions(repo, temp)
    shown = _git(repo, temp, "show", ["HEAD:big.txt"])
    export_dir = Path(shown["outputPath"]).parent

    external = permissions["external_directory"]
    assert export_dir.parent == temp
    assert is_run_owned_directory(str(export_dir))
    assert not export_dir.is_symlink()
    assert _last_match(external, f"{temp.as_posix()}/**") == "deny"
    assert _last_match(external, "/etc/**") == "deny"
    assert _last_match(external, f"{temp.as_posix()}/opencode-xdg-data/**") == "deny"
    assert _last_match(permissions["read"], f"{repo.as_posix()}/.git/config") == "deny"
    assert permissions["bash"] == "deny"
    assert permissions["edit"] == "deny"


def test_a_planted_export_directory_is_never_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another tenant of a shared temp dir cannot steer the grant or the writes."""
    repo, temp = _production_split(tmp_path, monkeypatch)
    victim = tmp_path / "victim"
    victim.mkdir()
    (temp / "git-read").symlink_to(victim, target_is_directory=True)
    (temp / "git-read-planted").symlink_to(victim, target_is_directory=True)

    shown = _git(repo, temp, "show", ["HEAD:big.txt"])

    export_dir = Path(shown["outputPath"]).parent
    assert export_dir.resolve().parent == temp.resolve()
    assert list(victim.iterdir()) == []
    external = _permissions(repo, temp)["external_directory"]
    assert _last_match(external, f"{victim.as_posix()}/**") == "deny"


def test_git_mutations_and_config_reads_stay_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, temp = _production_split(tmp_path, monkeypatch)
    tool = _tool(repo, temp)

    for command, args in (
        ("commit", ["-m", "x"]),
        ("show", ["HEAD:../../etc/passwd"]),
        ("grep", ["-h", "url", "--", ".git/config"]),
    ):
        result = asyncio.run(tool.execute({"command": command, "args": args}))
        assert result.is_error, (command, result.content)
