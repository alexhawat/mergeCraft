"""Long-option abbreviations must not slip past the git tool's exact-spelling guards.

git's parse-options resolves any unique prefix of a long option, so ``git grep
--no-inde`` is ``--no-index`` and ``git cat-file --tex`` is ``--textconv``.
Which prefixes are unique depends on the git release. Checked in the review
image's base (``python:3.14-slim-bookworm`` + apt ``git``, git 2.39.5):
``git cat-file --filter HEAD:t.txt`` and ``--filt`` run ``filter.<driver>.smudge``
(they abbreviate ``--filters``), and ``--filter=blob:none`` fails with "option
`filters' takes no value". On git 2.53, ``--filter`` is a separate object-filter
option. So the guards refuse every prefix of a refused option and forward an
exact name only when ``_EXACT_NAME_EXCEPTIONS`` lists it.

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
from mergecraft.mcp.git_guards import _EXACT_NAME_EXCEPTIONS, _REFUSED_LONG_OPTIONS
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


# --- exceptions -------------------------------------------------------------


@pytest.mark.parametrize(
    ("verb", "name"),
    [(verb, name) for verb, names in _EXACT_NAME_EXCEPTIONS.items() for name in names],
)
def test_each_exception_is_a_prefix_of_a_refused_option_but_not_one(verb: str, name: str) -> None:
    """An exception that prefixes nothing refused is dead; one that is refused is a hole."""
    refused = _REFUSED_LONG_OPTIONS[verb]
    assert name not in refused
    assert any(option.startswith(name) for option in refused)


# --- refused spellings ------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [*_prefixes("--no-index", "--n"), "--no-inde=x"],
)
def test_grep_refuses_every_no_index_spelling(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no-index"):
        _validate("grep", [token, "-n", "x"], tmp_path)


@pytest.mark.parametrize(
    "token",
    [
        *_prefixes("--untracked", "--u"),
        *_prefixes("--no-exclude-standard", "--n"),
    ],
)
def test_grep_refuses_untracked_and_ignored_file_scope(token: str, tmp_path: Path) -> None:
    # ``--n`` / ``--no`` / ``--no-`` also prefix ``--no-index`` and hit that guard first.
    with pytest.raises(ValueError, match=r"mergeCraft's own scratch|no-index"):
        _validate("grep", [token, "-n", "x"], tmp_path)


@pytest.mark.parametrize(
    "token",
    [
        *_prefixes("--textconv", "--t"),
        *_prefixes("--filters", "--f"),
        "--filter=blob:none",
    ],
)
def test_cat_file_refuses_every_content_filter_spelling(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command execution"):
        _validate("cat-file", [token, "HEAD:README.md"], tmp_path)


@pytest.mark.parametrize(
    "token",
    [
        *_prefixes("--contents", "--c"),
        "--contents=README.md",
        *(t for t in _prefixes("--ignore-revs-file", "--i") if t != "--ignore-rev"),
    ],
)
def test_blame_refuses_flag_valued_file_reads(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot confine"):
        _validate("blame", [token, "README.md"], tmp_path)


@pytest.mark.parametrize(
    "token", [*_prefixes("--upload-pack", "--u"), *_prefixes("--exec", "--e"), "--exe=x"]
)
def test_ls_remote_refuses_command_naming_options(token: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command execution"):
        _validate("ls-remote", [token, "origin"], tmp_path)


# --- a ``--`` that is an option value does not end options -------------------
# git consumes ``--`` as the value of ``-e`` (the first pattern), so a refused
# option after it still applies: ``git grep -e -- --untracked -e x`` searches
# untracked files. The guard scans every argument rather than trusting the split.


@pytest.mark.parametrize(
    ("verb", "args"),
    [
        ("grep", ["-e", "--", "--untracked", "-e", "x"]),
        ("grep", ["-e", "--", "--untr", "-e", "x"]),
        ("grep", ["-e", "--", "--no-exclude-standard", "-e", "x"]),
        ("grep", ["-e", "--", "--no-inde", "-e", "x"]),
        ("grep", ["-e--", "--untracked", "-e", "x"]),
        ("grep", ["-f", "--", "--untracked"]),
        ("blame", ["-L", "--", "--contents=README.md", "README.md"]),
        ("cat-file", ["--path", "--", "--tex", "HEAD:README.md"]),
        ("ls-remote", ["--sort", "--", "--upload-pack=x", "origin"]),
    ],
)
def test_option_after_a_swallowed_double_dash_is_refused(
    verb: str, args: list[str], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="Blocked"):
        _validate(verb, args, tmp_path)


def test_refused_option_spelling_after_a_real_double_dash_fails_closed(tmp_path: Path) -> None:
    """The guard cannot tell a real ``--`` from a swallowed one, so both are refused."""
    with pytest.raises(ValueError, match="mergeCraft's own scratch"):
        _validate("grep", ["-e", "x", "--", "--untracked"], tmp_path)


@pytest.mark.parametrize(
    "args",
    [["-e", "x", "--", "/some/repo/dir"], ["-e", "--", "/some/repo/dir"], ["-e", "--", "../x"]],
)
def test_path_confinement_holds_after_real_and_swallowed_double_dash(
    args: list[str], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="must be within"):
        _validate("grep", args, tmp_path)


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
        ("grep", ["-e", "x", "--", "README.md"]),
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
    ["-e", "--", "--untracked", "-e", "MC_TEST"],
    ["-e", "--", "--untracked", "--no-exclude-standard", "-e", "MC_TEST"],
    ["-e--", "--untr", "--no-exc", "-e", "MC_TEST"],
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


@pytest.mark.parametrize("args", [["-n", "MC_TEST"], ["-n", "-e", "MC_TEST", "--", "README.md"]])
async def test_plain_grep_still_searches_tracked_files_only(
    tmp_path: Path, args: list[str]
) -> None:
    root = _checkout_with_untracked_secrets(tmp_path)

    result = await git_tool(_ctx(root, "restricted")).execute({"command": "grep", "args": args})

    text = result.content[0]["text"]
    assert result.is_error is False, text
    assert "README.md:1:MC_TEST tracked line" in text
    assert AUTH_MARKER not in text
    assert ENV_MARKER not in text
