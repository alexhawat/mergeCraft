"""Review path ignoring (#1109): glob matching, input parsing, defaults and base-side config."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from mergecraft.config.settings import ReviewSettings
from mergecraft.review_policy.ignore_paths import (
    DEFAULT_IGNORE_PATHS,
    IGNORED_PATHS_HEADING,
    ReviewIgnore,
    build_review_ignore,
    filter_diff,
    glob_matches,
    list_pull_request_paths,
    merge_ignored_paths_into_review_body,
    parse_ignore_paths,
    resolve_review_ignore,
)

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider


def _as_scm(stub: object) -> ScmProvider:
    """The stubs implement only ``get``, the one method these readers call."""
    return cast("ScmProvider", stub)


# ── glob matching ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("host/evals/**/*.jsonl", "host/evals/a/b/c.jsonl", True),
        ("host/evals/**/*.jsonl", "host/evals/c.jsonl", True),
        ("host/evals/**/*.jsonl", "host/other/c.jsonl", False),
        ("host/evals/**/*.jsonl", "host/evals/c.json", False),
        ("**/*.lock", "uv.lock", True),
        ("**/*.lock", "a/b/Cargo.lock", True),
        ("**/CHANGELOG.md", "CHANGELOG.md", True),
        ("**/CHANGELOG.md", "packages/x/CHANGELOG.md", True),
        ("CHANGELOG.md", "CHANGELOG.md", True),
        ("CHANGELOG.md", "docs/CHANGELOG.md", False),
        ("*.md", "README.md", True),
        ("*.md", "docs/README.md", False),
        ("docs/**", "docs/a/b.png", True),
        ("docs/**", "src/docs.py", False),
        ("data/?.csv", "data/a.csv", True),
        ("data/?.csv", "data/ab.csv", False),
        ("data/[ab].csv", "data/b.csv", True),
        ("data/[!ab].csv", "data/b.csv", False),
        ("a.b", "axb", False),
    ],
)
def test_glob_matches_whole_path_with_recursive_double_star(
    pattern: str, path: str, *, expected: bool
) -> None:
    assert glob_matches(pattern, path) is expected


# ── input parsing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\n", ",,", [], ["", "  "]])
def test_empty_or_unset_input_parses_to_nothing(raw: Any) -> None:
    assert parse_ignore_paths(raw) == []


def test_newline_and_comma_separated_globs_are_both_split() -> None:
    raw = "host/evals/**/*.jsonl\nCHANGELOG.md, docs/*.png ,\n  ./fixtures/**\n# a comment\n"
    assert parse_ignore_paths(raw) == [
        "host/evals/**/*.jsonl",
        "CHANGELOG.md",
        "docs/*.png",
        "fixtures/**",
    ]


def test_duplicate_globs_are_dropped() -> None:
    assert parse_ignore_paths("a/**,a/**\na/**") == ["a/**"]


# ── defaults on / off ────────────────────────────────────────────────────────


def test_defaults_apply_when_nothing_is_configured() -> None:
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="test")
    assert ignore.patterns == DEFAULT_IGNORE_PATHS
    assert ignore.is_ignored("CHANGELOG.md")
    assert ignore.is_ignored("uv.lock")
    assert ignore.is_ignored("web/package-lock.json")
    assert ignore.is_ignored("static/app.min.js")
    assert not ignore.is_ignored("api/generated/client.py"), "a directory name is no proof"
    assert not ignore.is_ignored("src/app.py")
    assert not ignore.is_ignored("host/evals/case.jsonl"), "eval data is an example, not a default"


def test_defaults_off_reviews_changelogs_and_lockfiles() -> None:
    review = ReviewSettings.model_validate({"ignorePathDefaults": False})
    ignore = build_review_ignore(input_value="", review=review, source="test")
    assert ignore.patterns == ()
    assert ignore.active is False
    assert not ignore.is_ignored("CHANGELOG.md")
    assert not ignore.is_ignored("uv.lock")
    assert not ignore.is_ignored("static/app.min.js")


def test_defaults_off_still_honours_explicit_globs() -> None:
    review = ReviewSettings.model_validate(
        {"ignorePathDefaults": False, "ignorePaths": ["fixtures/**"]}
    )
    ignore = build_review_ignore(input_value="host/evals/**/*.jsonl", review=review, source="test")
    assert ignore.patterns == ("fixtures/**", "host/evals/**/*.jsonl")
    assert ignore.is_ignored("fixtures/a.json")
    assert ignore.is_ignored("host/evals/x/y.jsonl")
    assert not ignore.is_ignored("CHANGELOG.md")


def test_dropped_config_keeps_defaults_and_input() -> None:
    ignore = build_review_ignore(input_value="x/**", review=None, source="defaults")
    assert ignore.patterns == (*DEFAULT_IGNORE_PATHS, "x/**")


def test_a_generated_directory_is_reviewed_unless_a_glob_names_it() -> None:
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="test")
    assert ignore.partition(["api/generated/client.py", "src/app.py"]) == (
        ["api/generated/client.py", "src/app.py"],
        [],
    )
    review = ReviewSettings.model_validate({"ignorePaths": ["**/generated/**"]})
    opted = build_review_ignore(input_value=None, review=review, source="test")
    assert opted.partition(["api/generated/client.py", "src/app.py"]) == (
        ["src/app.py"],
        ["api/generated/client.py"],
    )


def test_settings_parse_camel_case_aliases() -> None:
    review = ReviewSettings.model_validate({"ignorePaths": ["a/**"], "ignorePathDefaults": False})
    assert review.ignore_paths == ["a/**"]
    assert review.ignore_path_defaults is False
    assert ReviewSettings().ignore_path_defaults is True
    assert ReviewSettings().ignore_paths == []


# ── diff filtering ───────────────────────────────────────────────────────────

_DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1 +1 @@\n"
    "-a = 1\n"
    "+a = 2\n"
    "diff --git a/CHANGELOG.md b/CHANGELOG.md\n"
    "--- a/CHANGELOG.md\n"
    "+++ b/CHANGELOG.md\n"
    "@@ -1 +1,2 @@\n"
    " # Changelog\n"
    "+- secret sauce\n"
    "diff --git a/host/evals/x/case.jsonl b/host/evals/x/case.jsonl\n"
    "--- a/host/evals/x/case.jsonl\n"
    "+++ b/host/evals/x/case.jsonl\n"
    "@@ -0,0 +1 @@\n"
    '+{"prompt": "eval payload"}\n'
)


def test_filter_diff_removes_ignored_sections_entirely() -> None:
    ignore = build_review_ignore(
        input_value="host/evals/**/*.jsonl\nCHANGELOG.md", review=ReviewSettings(), source="t"
    )
    filtered = filter_diff(_DIFF, ignore)
    assert filtered.ignored_paths == ["CHANGELOG.md", "host/evals/x/case.jsonl"]
    assert filtered.kept_paths == ["src/app.py"]
    assert "secret sauce" not in filtered.text
    assert "eval payload" not in filtered.text
    assert filtered.text.startswith("diff --git a/src/app.py b/src/app.py\n")
    assert "+a = 2\n" in filtered.text


def test_filter_diff_is_identity_without_a_matcher() -> None:
    assert filter_diff(_DIFF, None).text == _DIFF
    inactive = ReviewIgnore()
    assert filter_diff(_DIFF, inactive).text == _DIFF


def test_filter_diff_when_every_file_is_ignored_leaves_nothing() -> None:
    ignore = build_review_ignore(input_value="**", review=ReviewSettings(), source="t")
    filtered = filter_diff(_DIFF, ignore)
    assert filtered.text == ""
    assert filtered.kept_paths == []
    assert len(filtered.ignored_paths) == 3


def test_filter_diff_uses_the_post_image_of_a_rename() -> None:
    diff = (
        "diff --git a/CHANGELOG.md b/src/evil.py\n"
        "similarity index 90%\n"
        "rename from CHANGELOG.md\n"
        "rename to src/evil.py\n"
    )
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="t")
    assert filter_diff(diff, ignore).text == diff


def test_rename_into_an_ignored_name_stays_in_the_diff() -> None:
    diff = (
        "diff --git a/src/evil.py b/CHANGELOG.md\n"
        "similarity index 60%\n"
        "rename from src/evil.py\n"
        "rename to CHANGELOG.md\n"
        "@@ -1 +1 @@\n"
        "-def check(): return verify()\n"
        "+def check(): return True\n"
    )
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="t")
    filtered = filter_diff(diff, ignore)
    assert filtered.text == diff
    assert filtered.ignored_paths == []
    assert filtered.changed_paths == ["CHANGELOG.md", "src/evil.py"]


def test_copy_from_an_in_scope_file_into_an_ignored_name_stays_in_the_diff() -> None:
    diff = (
        "diff --git a/src/auth.py b/vendor.lock\n"
        "similarity index 100%\n"
        "copy from src/auth.py\n"
        "copy to vendor.lock\n"
    )
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="t")
    assert filter_diff(diff, ignore).text == diff


def test_rename_between_two_ignored_names_is_dropped() -> None:
    diff = (
        "diff --git a/CHANGELOG.md b/docs/CHANGELOG.md\n"
        "similarity index 100%\n"
        "rename from CHANGELOG.md\n"
        "rename to docs/CHANGELOG.md\n"
    )
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="t")
    filtered = filter_diff(diff, ignore)
    assert filtered.text == ""
    assert filtered.ignored_paths == ["docs/CHANGELOG.md"]


def test_rename_sources_maps_new_names_to_old() -> None:
    from mergecraft.review_policy.ignore_paths import rename_sources

    diff = "diff --git a/src/evil.py b/CHANGELOG.md\ndiff --git a/x.py b/x.py\n"
    assert rename_sources(diff) == {"CHANGELOG.md": "src/evil.py"}


def test_filter_diff_handles_quoted_headers() -> None:
    diff = 'diff --git "a/docs/my notes.md" "b/docs/my notes.md"\n@@ -0,0 +1 @@\n+x\n'
    ignore = build_review_ignore(input_value="docs/**", review=ReviewSettings(), source="t")
    assert filter_diff(diff, ignore).ignored_paths == ["docs/my notes.md"]


# ── review body ──────────────────────────────────────────────────────────────


def test_review_body_lists_ignored_files_once() -> None:
    body = merge_ignored_paths_into_review_body("Looks good.", ["CHANGELOG.md", "uv.lock"])
    assert IGNORED_PATHS_HEADING in body
    assert "- `CHANGELOG.md`" in body
    assert "- `uv.lock`" in body
    assert merge_ignored_paths_into_review_body(body, ["CHANGELOG.md"]) == body
    assert merge_ignored_paths_into_review_body("Looks good.", []) == "Looks good."
    assert IGNORED_PATHS_HEADING.endswith("Not reviewed (ignored by config)")


# ── base-side config resolution ──────────────────────────────────────────────


class _Scm:
    def __init__(self, *, contents: Any = None, error: Exception | None = None) -> None:
        self.contents = contents
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs.get("params") or {}))
        if self.error is not None:
            raise self.error
        return self.contents


def _file_payload(text: str) -> dict[str, Any]:
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(),
    }


def _pr_event() -> dict[str, Any]:
    return {"pull_request": {"number": 7, "base": {"sha": "b" * 40, "ref": "main"}}}


_HEAD_REVIEW = ReviewSettings.model_validate(
    {"ignorePaths": ["src/**"], "ignorePathDefaults": False}
)


@pytest.mark.asyncio
async def test_head_side_config_never_opts_a_pr_out_of_review() -> None:
    scm = _Scm(contents=_file_payload("review:\n  ignorePaths:\n    - fixtures/**\n"))
    ignore = await resolve_review_ignore(
        _as_scm(scm),
        "acme",
        "demo",
        event=_pr_event(),
        run_start_review=_HEAD_REVIEW,
        operator_owned=False,
        input_value=None,
    )
    assert ignore.source == "base_sha"
    assert not ignore.is_ignored("src/app.py"), "head config named src/**"
    assert ignore.is_ignored("fixtures/a.json")
    assert ignore.is_ignored("CHANGELOG.md"), "head config could not switch defaults off"
    assert scm.calls == [("/repos/acme/demo/contents/.mergecraft/config.yaml", {"ref": "b" * 40})]


@pytest.mark.asyncio
async def test_operator_owned_snapshot_is_used_directly() -> None:
    scm = _Scm(error=AssertionError("must not read"))
    ignore = await resolve_review_ignore(
        _as_scm(scm),
        "acme",
        "demo",
        event=_pr_event(),
        run_start_review=_HEAD_REVIEW,
        operator_owned=True,
        input_value="docs/**",
    )
    assert ignore.source == "base_snapshot"
    assert ignore.patterns == ("src/**", "docs/**")
    assert scm.calls == []


@pytest.mark.asyncio
async def test_base_without_config_uses_defaults_and_input() -> None:
    request = httpx.Request("GET", "https://api.github.test/x")
    missing = httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request)
    )
    ignore = await resolve_review_ignore(
        _as_scm(_Scm(error=missing)),
        "acme",
        "demo",
        event=_pr_event(),
        run_start_review=_HEAD_REVIEW,
        operator_owned=False,
        input_value="host/evals/**/*.jsonl",
    )
    assert ignore.source == "base_sha"
    assert ignore.patterns == (*DEFAULT_IGNORE_PATHS, "host/evals/**/*.jsonl")


@pytest.mark.parametrize(
    "scm",
    [
        _Scm(error=RuntimeError("boom")),
        _Scm(contents={"type": "symlink", "target": "/etc/passwd"}),
        _Scm(contents=_file_payload("review: [not, a, mapping]\n")),
    ],
)
@pytest.mark.asyncio
async def test_unreadable_base_config_drops_only_the_yaml_half(scm: _Scm) -> None:
    ignore = await resolve_review_ignore(
        _as_scm(scm),
        "acme",
        "demo",
        event=_pr_event(),
        run_start_review=_HEAD_REVIEW,
        operator_owned=False,
        input_value="x/**",
    )
    assert ignore.source == "defaults"
    assert ignore.detail
    assert ignore.patterns == (*DEFAULT_IGNORE_PATHS, "x/**")


@pytest.mark.asyncio
async def test_no_pull_request_uses_the_run_start_tree() -> None:
    ignore = await resolve_review_ignore(
        _as_scm(_Scm(error=AssertionError("must not read"))),
        "acme",
        "demo",
        event={},
        run_start_review=_HEAD_REVIEW,
        operator_owned=False,
        input_value=None,
    )
    assert ignore.source == "run_start_snapshot"
    assert ignore.patterns == ("src/**",)


# ── pull request listing ─────────────────────────────────────────────────────


class _FilesScm:
    def __init__(self, pages: dict[int, list[dict[str, Any]]]) -> None:
        self.pages = pages

    async def get(self, path: str, **kwargs: Any) -> Any:
        page = int((kwargs.get("params") or {}).get("page", 1))
        return self.pages.get(page, [])


@pytest.mark.asyncio
async def test_listing_returns_every_changed_path() -> None:
    scm = _FilesScm({1: [{"filename": "a.py"}, {"filename": "CHANGELOG.md"}]})
    assert await list_pull_request_paths(_as_scm(scm), "o", "r", 1) == ["a.py", "CHANGELOG.md"]


@pytest.mark.asyncio
async def test_listing_includes_rename_sources() -> None:
    scm = _FilesScm({1: [{"filename": "CHANGELOG.md", "previous_filename": "src/auth.py"}]})
    paths = await list_pull_request_paths(_as_scm(scm), "o", "r", 1)
    assert paths == ["CHANGELOG.md", "src/auth.py"]
    ignore = build_review_ignore(input_value=None, review=ReviewSettings(), source="t")
    assert ignore.partition(paths) == (["src/auth.py"], ["CHANGELOG.md"])


@pytest.mark.asyncio
async def test_truncated_or_failed_listing_is_doubt(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.review_policy import ignore_paths as module

    monkeypatch.setattr(module, "_FILES_MAX_PAGES", 2)
    full = [{"filename": f"f{i}.lock"} for i in range(100)]
    assert (
        await list_pull_request_paths(_as_scm(_FilesScm({1: full, 2: full})), "o", "r", 1) is None
    )
    assert (
        await list_pull_request_paths(_as_scm(_Scm(error=RuntimeError("x"))), "o", "r", 1) is None
    )
