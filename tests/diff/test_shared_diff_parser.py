"""The shared diff parser reads real ``git diff`` output the same way at every call site (#1306).

Every test builds a throwaway repository and diffs it with the real ``git``
binary, using Git's default ``core.quotePath=true``, so non-ASCII names arrive
C-quoted (``"caf\\303\\251.md"``) exactly as a review checkout produces them.
"""

from __future__ import annotations

import os
import subprocess
import unicodedata
from typing import TYPE_CHECKING, Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mergecraft.diff import (
    changed_paths_in_diff,
    diff_lines,
    parse_diff,
    split_diff_git_paths,
    unquote_git_path,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.diff import DiffFile

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [*_GIT, "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_GIT_ENV,
    )
    return result.stdout


def _write(repo: Path, rel: str, data: str | bytes) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        target.write_bytes(data)
    else:
        target.write_text(data, encoding="utf-8")


def _init(repo: Path, files: dict[str, str | bytes]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, data in files.items():
        _write(repo, rel, data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base", "--allow-empty")
    return _git(repo, "rev-parse", "HEAD").strip()


def _commit_and_diff(repo: Path, base: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    return _git(repo, "diff", "-M", base, "HEAD")


# Post-image path -> (status, pre-image path, binary)
_EXPECTED: dict[str, tuple[str, str | None, bool]] = {
    "café.md": ("added", None, False),
    "docs b/new.md": ("renamed", "docs b/old.md", False),
    "gone.py": ("deleted", "gone.py", False),
    "logo.bin": ("added", None, True),
    "my notes.txt": ("added", None, False),
    "new näme.txt": ("renamed", "old name.txt", False),
    "plain.py": ("modified", "plain.py", False),
    "run.sh": ("modified", "run.sh", False),
    "x b/y.txt": ("modified", "x b/y.txt", False),
}


@pytest.fixture
def mixed_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repository whose head commit touches every path shape git can emit."""
    repo = tmp_path / "repo"
    renamed_body = "".join(f"line {i}\n" for i in range(20))
    base = _init(
        repo,
        {
            "plain.py": "a = 1\n",
            "old name.txt": renamed_body,
            "docs b/old.md": renamed_body + "docs\n",
            "gone.py": "gone = True\n",
            "run.sh": "echo hi\n",
            "x b/y.txt": "one\n",
        },
    )
    _write(repo, "plain.py", "a = 2\n")
    _write(repo, "café.md", "# café\n")
    _write(repo, "my notes.txt", "notes\n")
    _write(repo, "logo.bin", b"\x00\x01\x02binary\x00")
    _write(repo, "x b/y.txt", "two\n")
    _git(repo, "mv", "old name.txt", "new näme.txt")
    _git(repo, "mv", "docs b/old.md", "docs b/new.md")
    _git(repo, "rm", "-q", "gone.py")
    (repo / "run.sh").chmod(0o755)
    return repo, _commit_and_diff(repo, base)


def _by_path(files: tuple[DiffFile, ...]) -> dict[str, DiffFile]:
    return {f.path: f for f in files if f.path is not None}


# ── the parser itself ────────────────────────────────────────────────────────


def test_real_diff_quotes_non_ascii_paths(mixed_repo: tuple[Path, str]) -> None:
    """Guard: the fixture really exercises Git's C-quoting, or the suite proves nothing."""
    _repo, diff = mixed_repo
    assert '"b/caf\\303\\251.md"' in diff
    assert 'rename to "new n\\303\\244me.txt"' in diff


def test_parse_diff_names_every_section_of_a_real_diff(mixed_repo: tuple[Path, str]) -> None:
    _repo, diff = mixed_repo
    parsed = parse_diff(diff)
    got = {path: (f.status, f.old_path, f.binary) for path, f in _by_path(parsed.files).items()}
    assert got == _EXPECTED
    assert parsed.preamble + "".join(f.text for f in parsed.files) == diff


def test_deleted_and_added_sections_have_one_side_only(mixed_repo: tuple[Path, str]) -> None:
    _repo, diff = mixed_repo
    files = _by_path(parse_diff(diff).files)
    assert (files["gone.py"].old_path, files["gone.py"].new_path) == ("gone.py", None)
    assert (files["café.md"].old_path, files["café.md"].new_path) == (None, "café.md")
    assert files["new näme.txt"].paths == ("new näme.txt", "old name.txt")


def test_changed_paths_lists_post_images_and_can_drop_deletions(
    mixed_repo: tuple[Path, str],
) -> None:
    _repo, diff = mixed_repo
    assert sorted(changed_paths_in_diff(diff)) == sorted(_EXPECTED)
    assert "gone.py" not in changed_paths_in_diff(diff, include_deleted=False)
    assert len(changed_paths_in_diff(diff, include_deleted=False)) == len(_EXPECTED) - 1


def test_added_line_that_looks_like_a_header_is_content(tmp_path: Path) -> None:
    """Inside a hunk ``+++ b/evil`` is an added line ``++ b/evil``, never a path."""
    repo = tmp_path / "repo"
    base = _init(repo, {"notes.md": "x\n"})
    _write(repo, "notes.md", "x\n++ b/evil\n-- a/other\n")
    diff = _commit_and_diff(repo, base)
    assert "\n+++ b/evil\n" in diff
    assert changed_paths_in_diff(diff) == ["notes.md"]


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ('"caf\\303\\251.md"', "café.md"),
        ('"tab\\there"', "tab\there"),
        ('"q\\"uote"', 'q"uote'),
        ("plain name.txt", "plain name.txt"),
        ('"unterminated', None),
        ('"bad\\777"', None),
    ],
    ids=["non-ascii", "tab", "quote", "unquoted-space", "unterminated", "invalid-utf8"],
)
def test_unquote_git_path(token: str, expected: str | None) -> None:
    assert unquote_git_path(token) == expected


def test_ambiguous_unquoted_header_defers_to_extended_lines() -> None:
    assert split_diff_git_paths("a/x b/y b/x b/z") is None
    assert split_diff_git_paths("a/x b/y b/x b/y") == ("x b/y", "x b/y")


_NAME_CHARS = st.sampled_from([*"abcXY _-.é日ü\"'b/", "\t"])


def _valid_name(name: str) -> bool:
    parts = name.split("/")
    if parts[0] == ".git":
        return False
    return all(part.strip() and part not in {".", ".."} and part == part.strip() for part in parts)


_NAMES = st.text(_NAME_CHARS, min_size=1, max_size=12).filter(_valid_name)


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.filter_too_much],
)
@given(
    names=st.lists(_NAMES, min_size=1, max_size=4, unique_by=lambda n: n.casefold()),
    rename=st.booleans(),
)
def test_property_parser_recovers_every_path_git_writes(
    tmp_path_factory: pytest.TempPathFactory, names: list[str], rename: bool
) -> None:
    """For any set of awkward names, the paths git diffs are the paths we read back."""
    names = [unicodedata.normalize("NFC", n) for n in names]
    # A path that is a prefix-directory of another cannot coexist on disk.
    if any(a != b and b.startswith(a + "/") for a in names for b in names):
        return
    repo = tmp_path_factory.mktemp("prop") / "repo"
    body = "".join(f"row {i}\n" for i in range(12))
    base = _init(repo, {"seed.txt": body, **dict.fromkeys(names, "old\n")})
    for name in names:
        _write(repo, name, "new\n")
    expected = set(names)
    if rename:
        target = "moved " + names[0].replace("/", "_") + ".txt"
        if target not in names:
            _git(repo, "mv", "seed.txt", target)
            expected.add(target)
    diff = _commit_and_diff(repo, base)
    assert set(changed_paths_in_diff(diff)) == expected


_SEPARATOR_CONTENT = "x\u2028diff --git a/elsewhere.py b/elsewhere.py\n"


@pytest.fixture
def separator_repo(tmp_path: Path) -> tuple[Path, str]:
    """A file whose added content holds a Unicode line separator before header-like text."""
    repo = tmp_path / "repo"
    base = _init(repo, {"notes.md": "start\n"})
    _write(repo, "notes.md", "start\n" + _SEPARATOR_CONTENT + "after the separator\n")
    return repo, _commit_and_diff(repo, base)


def test_unicode_line_separators_in_content_do_not_start_sections(
    separator_repo: tuple[Path, str],
) -> None:
    """Only ``\\n`` ends a diff line, as in Git; content cannot open a new section."""
    _repo, diff = separator_repo
    assert "\u2028diff --git a/elsewhere.py" in diff
    parsed = parse_diff(diff)
    assert [f.path for f in parsed.files] == ["notes.md"]
    assert changed_paths_in_diff(diff) == ["notes.md"]
    assert len(diff_lines(diff)) == diff.count("\n")
    assert "".join(diff_lines(diff, keepends=True)) == diff


def test_call_sites_keep_the_whole_file_when_content_holds_a_separator(
    separator_repo: tuple[Path, str],
) -> None:
    from mergecraft.agents_sdk.change_data import _confine_diff_paths
    from mergecraft.analyzers.impact import _parse_hunks
    from mergecraft.mcp.inline_anchors import build_inline_anchor_index
    from mergecraft.offline_review import _filter_diff_to_paths

    repo, diff = separator_repo
    assert _filter_diff_to_paths(diff, ["notes.md"]) == diff
    assert _confine_diff_paths(repo, diff) == (diff, ["notes.md"])
    assert set(_parse_hunks(diff)) == {"notes.md"}
    index = build_inline_anchor_index(diff)
    assert set(index.hunk_ranges) == {"notes.md"}
    assert ("notes.md", 3, "RIGHT") in index.anchors


# ── real call sites ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_scope_accepts_an_honest_diff_with_quoted_paths(
    mixed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    """``establish_review_scope``'s PR binding no longer reports quoted files as missing."""
    from mergecraft.mcp.verdict import reject_diff_that_does_not_match_the_pr
    from tests.support.github_fakes import StrictGitHubClient
    from tests.support.tool_context import make_tool_context

    _repo, diff = mixed_repo
    files: list[dict[str, Any]] = []
    for path, (status, pre, _binary) in _EXPECTED.items():
        entry: dict[str, Any] = {"filename": path, "status": status}
        if status == "renamed":
            entry["previous_filename"] = pre
        files.append(entry)
    github = StrictGitHubClient(routes={("GET", "/repos/acme/demo/pulls/7/files"): files})
    ctx = make_tool_context(tmp_path, trust_tier="untrusted", github=github)
    diff_path = tmp_path / "pr.diff"
    diff_path.write_text(diff, encoding="utf-8")

    await reject_diff_that_does_not_match_the_pr(ctx, diff_path=str(diff_path), pull_number=7)

    files.append({"filename": "unlisted.py", "status": "added"})
    with pytest.raises(ValueError, match="missing 1 file"):
        await reject_diff_that_does_not_match_the_pr(ctx, diff_path=str(diff_path), pull_number=7)


def test_offline_confinement_filter_keeps_quoted_sections(mixed_repo: tuple[Path, str]) -> None:
    """The untrusted offline diff filter keeps a kept file's hunks even when git quoted it."""
    from mergecraft.offline_review import _filter_diff_to_paths

    _repo, diff = mixed_repo
    kept = _filter_diff_to_paths(diff, ["café.md", "new näme.txt", "plain.py"])
    assert sorted(changed_paths_in_diff(kept)) == ["café.md", "new näme.txt", "plain.py"]
    assert "+# café" in kept


def test_agents_sdk_confinement_keeps_every_in_workspace_path(
    mixed_repo: tuple[Path, str],
) -> None:
    from mergecraft.agents_sdk.change_data import _confine_diff_paths

    repo, diff = mixed_repo
    text, paths = _confine_diff_paths(repo, diff)
    assert sorted(paths) == sorted(_EXPECTED)
    assert text == diff


def test_ignore_paths_matches_decoded_names_and_keeps_renames(
    mixed_repo: tuple[Path, str],
) -> None:
    """``ignorePaths`` globs see ``café.md``, not ``caf\\303\\251.md``."""
    from mergecraft.review_policy.ignore_paths import ReviewIgnore, filter_diff, rename_sources

    _repo, diff = mixed_repo
    result = filter_diff(diff, ReviewIgnore(patterns=("*.md",)))
    assert "café.md" in result.ignored_paths
    assert "new näme.txt" in result.kept_paths
    assert set(result.changed_paths) >= {"café.md", "old name.txt", "new näme.txt"}
    assert rename_sources(diff)["new näme.txt"] == "old name.txt"


def test_inline_anchors_index_quoted_paths(mixed_repo: tuple[Path, str]) -> None:
    from mergecraft.mcp.inline_anchors import build_inline_anchor_index

    _repo, diff = mixed_repo
    index = build_inline_anchor_index(diff)
    assert ("café.md", 1, "RIGHT") in index.anchors
    assert ("my notes.txt", 1, "RIGHT") in index.anchors
    assert "café.md" in index.hunk_ranges
    assert "caf\\303\\251.md" not in index.hunk_ranges


def test_impact_hunks_cover_quoted_paths(mixed_repo: tuple[Path, str]) -> None:
    from mergecraft.analyzers.impact import _parse_hunks

    _repo, diff = mixed_repo
    hunks = _parse_hunks(diff)
    assert hunks["café.md"] == [(1, 1)]
    assert "plain.py" in hunks


@pytest.mark.asyncio
async def test_offline_analyze_hands_analyzers_quoted_paths(
    mixed_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The offline analyze stage passes the decoded non-ASCII path to the pipeline."""
    from mergecraft.mcp.tool_state import AnalyzerRunState
    from mergecraft.review import offline_stages
    from mergecraft.utils.offline_diff import DiffMaterialization

    repo, diff = mixed_repo
    diff_file = repo.parent / "head.diff"
    diff_file.write_text(diff, encoding="utf-8")
    seen: dict[str, Any] = {}

    def _pipeline(**kwargs: Any) -> AnalyzerRunState:
        seen.update(kwargs)
        return AnalyzerRunState(ran=True)

    monkeypatch.setattr(offline_stages, "run_analyzer_pipeline", _pipeline)
    materialization = DiffMaterialization(
        path=diff_file, base_ref="main", line_count=diff.count("\n"), empty=False
    )
    await offline_stages.run_offline_analyze(
        cwd=repo, materialization=materialization, trust_tier="untrusted"
    )
    assert "café.md" in seen["changed_files"]
    assert "new näme.txt" in seen["changed_files"]
