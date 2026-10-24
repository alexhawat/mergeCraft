"""Long-option abbreviations must not slip past the git tool's exact-spelling guards.

git's parse-options resolves any unique prefix of a long option, so ``git grep
--no-inde`` is ``--no-index`` and ``git cat-file --tex`` is ``--textconv``. The
guards resolve each token against the verb's pinned option list instead of
matching one spelling.

The checkout test builds what a CI run can leave in the working tree — an
untracked OpenCode ``auth.json`` under ``.mergecraft/prep-scratch/`` and an
ignored ``.env`` — and asserts no spelling the tool forwards surfaces either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.git import _validate_git_invocation, git_tool
from mergecraft.mcp.git_guards import (
    _BLAME_LONG_OPTIONS,
    _CAT_FILE_LONG_OPTIONS,
    _GREP_LONG_OPTIONS,
    _LS_REMOTE_LONG_OPTIONS,
    _REFUSED_LONG_OPTIONS,
    long_option_candidates,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

AUTH_MARKER = "MC_TEST_AUTH_MARKER"
ENV_MARKER = "MC_TEST_ENV_MARKER"
AUTH_REL = ".mergecraft/prep-scratch/opencode-xdg-data/opencode/auth.json"


def _validate(command: str, args: list[str], cwd: Path) -> None:
    _validate_git_invocation(command, args, [], str(cwd), tmpdir="")


def _prefixes(option: str, shortest: str) -> list[str]:
    """Every spelling from *shortest* up to the full *option*."""
    return [option[:end] for end in range(len(shortest), len(option) + 1)]


# --- resolver ---------------------------------------------------------------


def test_exact_name_wins_over_longer_options() -> None:
    assert long_option_candidates("--text", _GREP_LONG_OPTIONS) == {"--text"}
    assert long_option_candidates("--filter", _CAT_FILE_LONG_OPTIONS) == {"--filter"}


def test_unique_prefix_resolves_and_value_is_ignored() -> None:
    assert long_option_candidates("--no-inde", _GREP_LONG_OPTIONS) == {"--no-index"}
    assert long_option_candidates("--cont=x", _BLAME_LONG_OPTIONS) == {"--contents"}


def test_ambiguous_prefix_returns_every_candidate() -> None:
    assert long_option_candidates("--no-in", _GREP_LONG_OPTIONS) == {
        "--no-index",
        "--no-invert-match",
    }


@pytest.mark.parametrize("token", ["-n", "pattern", "--", ""])
def test_non_long_option_names_nothing(token: str) -> None:
    assert long_option_candidates(token, _GREP_LONG_OPTIONS) == frozenset()


@pytest.mark.parametrize(
    ("verb", "options"),
    [
        ("grep", _GREP_LONG_OPTIONS),
        ("cat-file", _CAT_FILE_LONG_OPTIONS),
        ("blame", _BLAME_LONG_OPTIONS),
        ("ls-remote", _LS_REMOTE_LONG_OPTIONS),
    ],
)
def test_every_refused_option_is_in_its_verbs_pinned_list(
    verb: str, options: frozenset[str]
) -> None:
    """A refused name missing from the list would never resolve, so never refuse."""
    assert set(_REFUSED_LONG_OPTIONS[verb]) <= options


# --- refused spellings ------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [*_prefixes("--no-index", "--no-ind"), "--no-in", "--no-inde=x"],
)
def test_grep_refuses_every_no_index_spelling(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no-index"):
        _validate("grep", [token, "-n", "x"], tmp_path)


@pytest.mark.parametrize(
    "token",
    [
        *_prefixes("--untracked", "--u"),
        *_prefixes("--no-exclude-standard", "--no-e"),
    ],
)
def test_grep_refuses_untracked_and_ignored_file_scope(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mergeCraft's own scratch"):
        _validate("grep", [token, "-n", "x"], tmp_path)


@pytest.mark.parametrize(
    "token", [*_prefixes("--textconv", "--t"), *_prefixes("--filters", "--filters")]
)
def test_cat_file_refuses_every_content_filter_spelling(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command execution"):
        _validate("cat-file", [token, "HEAD:README.md"], tmp_path)


@pytest.mark.parametrize(
    "token",
    [
        *_prefixes("--contents", "--cont"),
        "--contents=README.md",
        *_prefixes("--ignore-revs-file", "--ignore-revs"),
    ],
)
def test_blame_refuses_flag_valued_file_reads(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot confine"):
        _validate("blame", [token, "README.md"], tmp_path)


@pytest.mark.parametrize("token", [*_prefixes("--upload-pack", "--u"), "--exec", "--exe=x"])
def test_ls_remote_refuses_command_naming_options(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command execution"):
        _validate("ls-remote", [token, "origin"], tmp_path)


# --- neighbouring options stay usable ---------------------------------------


@pytest.mark.parametrize(
    ("verb", "args"),
    [
        ("grep", ["--index", "-n", "x"]),
        ("grep", ["--exclude-standard", "-n", "x"]),
        ("grep", ["--no-untracked", "-n", "x"]),
        ("grep", ["--no-invert-match", "-n", "x"]),
        ("grep", ["--text", "-n", "x"]),
        ("grep", ["--cached", "-n", "x"]),
        ("grep", ["-n", "x", "--", "--untracked"]),
        ("cat-file", ["--filter=blob:none", "--batch-all-objects", "--batch-check"]),
        ("cat-file", ["--batch-check"]),
        ("blame", ["--porcelain", "README.md"]),
        ("blame", ["--no-contents", "README.md"]),
        ("blame", ["--ignore-rev", "HEAD", "README.md"]),
        ("ls-remote", ["--tags", "origin"]),
        ("ls-remote", ["--no-upload-pack", "origin"]),
    ],
)
def test_neighbouring_options_are_forwarded(verb: str, args: list[str], tmp_path: Path) -> None:
    _validate(verb, args, tmp_path)


# --- real checkout ----------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _checkout_with_untracked_secrets(root: Path) -> Path:
    """A repo whose tracked file matches, with an untracked and an ignored secret."""
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    (root / "README.md").write_text("MC_TEST tracked line\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    auth = root / AUTH_REL
    auth.parent.mkdir(parents=True)
    auth.write_text(f'{{"key": "MC_TEST {AUTH_MARKER}"}}\n', encoding="utf-8")
    (root / ".env").write_text(f"TOKEN=MC_TEST {ENV_MARKER}\n", encoding="utf-8")
    return root


def _ctx(root: Path, shell: Literal["disabled", "restricted", "enabled"]) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request"), shell=shell),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(root)),
        mcp_server_url="",
        tmpdir=str(root),
        trust_tier="trusted",
    )


_SCOPE_WIDENING_ARGS: list[list[str]] = [
    ["--no-index", "-n", "MC_TEST"],
    ["--no-inde", "-n", "MC_TEST"],
    ["--no-ind", "-n", "MC_TEST"],
    ["--untracked", "-n", "MC_TEST"],
    ["--untr", "-n", "MC_TEST"],
    ["--untracked", "--no-exclude-standard", "-n", "MC_TEST"],
    ["--u", "--no-exc", "-n", "MC_TEST"],
]


@pytest.mark.parametrize("shell", ["restricted", "enabled"])
@pytest.mark.parametrize("args", _SCOPE_WIDENING_ARGS)
async def test_git_tool_cannot_surface_untracked_or_ignored_secrets(
    tmp_path: Path, args: list[str], shell: Literal["restricted", "enabled"]
) -> None:
    root = _checkout_with_untracked_secrets(tmp_path)

    result = await git_tool(_ctx(root, shell)).execute({"command": "grep", "args": args})

    text = result.content[0]["text"]
    assert result.is_error is True, text
    assert AUTH_MARKER not in text
    assert ENV_MARKER not in text


@pytest.mark.parametrize(
    "args", [["--contents", AUTH_REL, "README.md"], ["--cont=.env", "README.md"]]
)
async def test_git_tool_blame_cannot_read_untracked_secrets(
    tmp_path: Path, args: list[str]
) -> None:
    root = _checkout_with_untracked_secrets(tmp_path)

    result = await git_tool(_ctx(root, "restricted")).execute({"command": "blame", "args": args})

    text = result.content[0]["text"]
    assert result.is_error is True, text
    assert AUTH_MARKER not in text
    assert ENV_MARKER not in text


async def test_plain_grep_still_searches_tracked_files_only(tmp_path: Path) -> None:
    root = _checkout_with_untracked_secrets(tmp_path)

    result = await git_tool(_ctx(root, "restricted")).execute(
        {"command": "grep", "args": ["-n", "MC_TEST"]}
    )

    text = result.content[0]["text"]
    assert result.is_error is False, text
    assert "README.md:1:MC_TEST tracked line" in text
    assert AUTH_MARKER not in text
    assert ENV_MARKER not in text
