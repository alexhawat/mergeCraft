"""Review path ignoring: keep changelogs, lockfiles and minified files out of the diff.

``ignore_paths`` (Action input) and ``review.ignorePaths`` (repo config) name globs whose
changed files the reviewer never sees. A built-in default set (changelogs, lockfiles and
minified files) applies unless ``review.ignorePathDefaults: false``. A directory named
``generated`` is not proof of generated output, so it is reviewed unless a glob such as
``**/generated/**`` opts it out.

The repo config half is only ever read from the operator's side of the pull request: the
run-start snapshot on a ``pull_request_target`` run (the base checkout), the base commit
through the contents API on any other pull request run, and the run-start tree when there
is no pull request at all. A pull request's own ``.mergecraft/config.yaml`` can therefore
never opt its own files out of review. Any doubt about the base config drops the YAML
half and keeps the defaults and the Action input, which the workflow file owns.

Glob semantics follow GitHub's workflow ``paths`` filters: the pattern matches the whole
repository-relative path, ``*`` and ``?`` stop at ``/``, and ``**`` crosses directories
(``**/`` also matches zero directories).

Module: mergecraft.review_policy.ignore_paths
Depends: mergecraft.classify.generated_files, mergecraft.config.settings

Exports:
    DEFAULT_IGNORE_PATHS: The opt-out default globs.
    IGNORED_PATHS_HEADING: Heading of the review-body section that lists ignored files.
    ReviewIgnore: The resolved matcher and where its config came from.
    FilteredDiff: A unified diff with the ignored file sections removed.
    parse_ignore_paths: Split a newline- or comma-separated glob list.
    glob_matches: Whether one glob matches one repository path.
    build_review_ignore: Assemble a matcher from the input, the settings and the defaults.
    filter_diff: Drop ignored file sections from a unified diff.
    resolve_review_ignore: Read the operator-side config and build the run's matcher.
    list_pull_request_paths: Every changed path of a pull request, or ``None`` on doubt.
    ignored_paths_section: The review-body section naming the ignored files.
    merge_ignored_paths_into_review_body: Append that section once.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.classify.generated_files import (
    FileKind,
    classify_path,
)
from mergecraft.classify.path_globs import path_full_matches_glob
from mergecraft.diff import parse_diff

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mergecraft.config.settings import RepoSettings, ReviewSettings
    from mergecraft.scm.protocol import ScmProvider

DEFAULT_IGNORE_PATHS: Final[tuple[str, ...]] = (
    "**/CHANGELOG.md",
    "**/*.lock",
    "**/package-lock.json",
)
"""Default globs. ``**/*.lock`` covers ``uv.lock``, ``Cargo.lock``, ``poetry.lock`` and
``yarn.lock``; minified files are matched by
:func:`mergecraft.classify.generated_files.classify_path` on top of these."""

IGNORED_PATHS_HEADING: Final[str] = "### Not reviewed (ignored by config)"
INPUT_ENV: Final[str] = "INPUT_IGNORE_PATHS"
_CONFIG_REL: Final[str] = ".mergecraft/config.yaml"
_MAX_CONFIG_BYTES: Final[int] = 1024 * 1024
_FILES_PAGE_SIZE: Final[int] = 100
_FILES_MAX_PAGES: Final[int] = 30
_SECTION_LIST_CAP: Final[int] = 50
_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[\n,]")


def parse_ignore_paths(raw: str | Iterable[str] | None) -> list[str]:
    """Split a newline- or comma-separated glob list; drop blanks and ``#`` comments.

    Args:
        raw: The Action input text, or an already-split list (repo config).

    Returns:
        The globs in order, stripped, de-duplicated, with a leading ``./`` or ``/`` removed.

    Examples:
        >>> parse_ignore_paths("host/evals/**/*.jsonl\\nCHANGELOG.md, docs/*.png")
        ['host/evals/**/*.jsonl', 'CHANGELOG.md', 'docs/*.png']
    """
    if raw is None:
        return []
    items = _SPLIT_RE.split(raw) if isinstance(raw, str) else list(raw)
    out: dict[str, None] = {}
    for item in items:
        glob = str(item).strip().replace("\\", "/")
        if not glob or glob.startswith("#"):
            continue
        while glob.startswith(("./", "/")):
            glob = glob.removeprefix("./").removeprefix("/")
        if glob:
            out.setdefault(glob, None)
    return list(out)


def glob_matches(pattern: str, path: str) -> bool:
    """Return whether ``pattern`` matches the whole repository-relative ``path``.

    The dialect is the one policy scopes and declared Scope paths read
    (:func:`mergecraft.classify.path_globs.path_full_matches_glob`), so one glob
    means the same thing in ``review.ignorePaths`` and in a policy rule.

    Examples:
        >>> glob_matches("**/*.lock", "uv.lock"), glob_matches("*.md", "docs/a.md")
        (True, False)
    """
    return path_full_matches_glob(pattern, path)


@dataclass(frozen=True, slots=True)
class ReviewIgnore:
    """The run's review path matcher.

    Attributes:
        patterns: Every glob in force (defaults first, then config, then the input).
        generated_defaults: Whether minified files are ignored too (the defaults are on).
        source: Where the repo-config half came from (for the run log).
        detail: Why the repo-config half was dropped, when it was.
    """

    patterns: tuple[str, ...] = ()
    generated_defaults: bool = False
    source: str = "none"
    detail: str | None = None

    @property
    def active(self) -> bool:
        """Whether anything can be ignored at all."""
        return bool(self.patterns) or self.generated_defaults

    def is_ignored(self, path: str, *, changed_paths: Sequence[str] = ()) -> bool:
        """Return whether ``path`` is kept out of review.

        The built-in default drops minified bundles (``*.min.js``, ``*.min.css``) by
        name. A path under a ``generated/`` directory is reviewed unless a glob names
        it: the directory name alone does not prove the file is generator output.
        ``changed_paths`` is accepted for callers that pass the pull request's change
        set; the name-only rule does not read it.
        """
        del changed_paths
        if any(glob_matches(pattern, path) for pattern in self.patterns):
            return True
        return self.generated_defaults and classify_path(path) == FileKind.MINIFIED

    def all_ignored(self, paths: Sequence[str], *, changed_paths: Sequence[str] = ()) -> bool:
        """Return whether every path one change names is ignored.

        A rename or copy names a pre-image and a post-image; it leaves review only when
        both are ignored, so ``git mv src/auth.py CHANGELOG.md`` stays in scope.
        """
        return bool(paths) and all(
            self.is_ignored(path, changed_paths=changed_paths) for path in paths
        )

    def partition(self, paths: Sequence[str]) -> tuple[list[str], list[str]]:
        """Split ``paths`` into ``(kept, ignored)``, preserving order."""
        kept: list[str] = []
        ignored: list[str] = []
        for path in paths:
            (ignored if self.is_ignored(path, changed_paths=paths) else kept).append(path)
        return kept, ignored


def build_review_ignore(
    *,
    input_value: str | None,
    review: ReviewSettings | None,
    source: str,
    detail: str | None = None,
) -> ReviewIgnore:
    """Assemble the matcher: defaults (unless switched off), config globs, input globs.

    Args:
        input_value: The raw ``ignore_paths`` Action input.
        review: The operator-side ``review`` settings, or ``None`` when they were dropped.
        source: Where ``review`` came from.
        detail: Why ``review`` was dropped, when it was.
    """
    defaults = review.ignore_path_defaults if review is not None else True
    patterns: list[str] = list(DEFAULT_IGNORE_PATHS) if defaults else []
    if review is not None:
        patterns.extend(parse_ignore_paths(review.ignore_paths))
    patterns.extend(parse_ignore_paths(input_value))
    return ReviewIgnore(
        patterns=tuple(dict.fromkeys(patterns)),
        generated_defaults=defaults,
        source=source,
        detail=detail,
    )


@dataclass(frozen=True, slots=True)
class FilteredDiff:
    """A unified diff with the ignored file sections removed.

    Attributes:
        text: The diff the reviewer is handed.
        ignored_paths: Post-image paths whose sections were removed, in diff order.
        kept_paths: Post-image paths that stayed, in diff order.
    """

    text: str
    ignored_paths: list[str] = field(default_factory=list)
    kept_paths: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    """Every path the diff names, rename and copy pre-images included."""


def _split_sections(diff_text: str) -> tuple[str, list[tuple[tuple[str, ...], str]]]:
    """``(preamble, [((post-image, pre-image), section text)])``; ``()`` paths if unparsable."""
    parsed = parse_diff(diff_text)
    return parsed.preamble, [(section.paths, section.text) for section in parsed.files]


def rename_sources(diff_text: str) -> dict[str, str]:
    """Map each renamed or copied post-image path in ``diff_text`` to its pre-image."""
    _prefix, sections = _split_sections(str(diff_text))
    return {paths[0]: paths[1] for paths, _ in sections if len(paths) == 2}


def filter_diff(
    diff_text: str,
    ignore: ReviewIgnore | None,
    *,
    changed_paths: Sequence[str] | None = None,
) -> FilteredDiff:
    """Drop the file sections of ``diff_text`` whose every named path is ignored.

    A rename or copy section names a pre-image and a post-image, and is dropped only
    when both are ignored: renaming ``src/auth.py`` to ``CHANGELOG.md`` stays in review,
    so a pull request cannot take a file out of scope by renaming it into an ignored
    name. ``ignored_paths`` and ``kept_paths`` report post-image paths.

    ``changed_paths`` is the whole pull request's change set, used by the generated-file
    rule (a generated file stays in scope when its generator config changed anywhere in
    the PR). Pass it whenever ``diff_text`` covers less than the full PR, such as an
    incremental range; without it the diff's own paths are the change set. A section
    whose header cannot be parsed is kept: an unreadable header is never a reason to
    review less.
    """
    prefix, sections = _split_sections(str(diff_text))
    posts = list(dict.fromkeys(paths[0] for paths, _ in sections if paths))
    every = list(dict.fromkeys(path for paths, _ in sections for path in paths))
    if ignore is None or not ignore.active:
        return FilteredDiff(text=str(diff_text), kept_paths=posts, changed_paths=every)
    change_set = list(dict.fromkeys([*every, *(changed_paths or ())]))
    kept_parts: list[str] = [prefix]
    ignored: list[str] = []
    kept: list[str] = []
    for paths, body in sections:
        if ignore.all_ignored(paths, changed_paths=change_set):
            ignored.append(paths[0])
            continue
        if paths:
            kept.append(paths[0])
        kept_parts.append(body)
    return FilteredDiff(
        text="".join(kept_parts),
        ignored_paths=list(dict.fromkeys(ignored)),
        kept_paths=list(dict.fromkeys(kept)),
        changed_paths=every,
    )


def _http_status(err: BaseException) -> int | None:
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _repo_settings_from_text(text: str) -> RepoSettings:
    from mergecraft.analyzers.settings_pin import repo_settings_from_text

    return repo_settings_from_text(text)


async def _base_repo_settings(
    scm: ScmProvider, owner: str, repo: str, base_sha: str
) -> tuple[RepoSettings | None, str, str | None]:
    """Share one parsed base config or fail-closed outcome for this run."""
    from mergecraft.scm.run_data import read_run_data

    return await read_run_data(
        scm,
        ("base-settings", owner, repo, base_sha),
        lambda: _read_base_repo_settings(scm, owner, repo, base_sha),
    )


async def _read_base_repo_settings(
    scm: ScmProvider, owner: str, repo: str, base_sha: str
) -> tuple[RepoSettings | None, str, str | None]:
    """Read the base commit's whole config through the contents API.

    A base without the file is the defaults; an unreadable, oversized or invalid one
    is ``None`` with the reason, so each caller fails toward its own safe side.
    """
    from mergecraft.config.settings import default_settings

    try:
        payload = await scm.get(
            f"/repos/{owner}/{repo}/contents/{_CONFIG_REL}", params={"ref": base_sha}
        )
    except Exception as err:  # an unreadable base config drops the YAML half, never the review
        if _http_status(err) == 404:
            return default_settings(), "base_sha", f"the PR base has no {_CONFIG_REL}"
        return None, "defaults", f"the PR base config could not be read ({type(err).__name__})"
    if not isinstance(payload, dict) or payload.get("type") != "file":
        return None, "defaults", f"{_CONFIG_REL} at the PR base is not a regular file"
    if payload.get("encoding") != "base64":
        return None, "defaults", f"{_CONFIG_REL} at the PR base has no inline content"
    try:
        raw = base64.b64decode(str(payload.get("content") or ""))
        if len(raw) > _MAX_CONFIG_BYTES:
            return None, "defaults", f"{_CONFIG_REL} at the PR base is too large"
        return _repo_settings_from_text(raw.decode("utf-8")), "base_sha", None
    except Exception as err:  # a malformed base config fails toward reviewing more
        return None, "defaults", f"{_CONFIG_REL} at the PR base is invalid ({err})"


async def _base_review_settings(
    scm: ScmProvider, owner: str, repo: str, base_sha: str
) -> tuple[ReviewSettings | None, str, str | None]:
    """Read ``review`` settings from the base commit's config through the contents API."""
    settings, source, detail = await _base_repo_settings(scm, owner, repo, base_sha)
    return (settings.review if settings is not None else None), source, detail


def _event_base_sha(event: dict[str, Any] | None) -> str:
    pull = event.get("pull_request") if isinstance(event, dict) else None
    base = pull.get("base") if isinstance(pull, dict) else None
    sha = base.get("sha") if isinstance(base, dict) else None
    return sha.strip() if isinstance(sha, str) else ""


async def resolve_review_ignore(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    event: dict[str, Any] | None,
    run_start_review: ReviewSettings,
    operator_owned: bool,
    input_value: str | None,
) -> ReviewIgnore:
    """Build the run's matcher from operator-side config only.

    Args:
        scm: Provider used to read the base config on a non-operator-owned PR run.
        owner: Repository owner.
        repo: Repository name.
        event: The bound GitHub event (its ``pull_request.base.sha`` names the base).
        run_start_review: ``review`` settings from the run-start tree.
        operator_owned: Whether the run-start tree is the base (``pull_request_target``).
        input_value: The raw ``ignore_paths`` Action input.
    """
    pull = event.get("pull_request") if isinstance(event, dict) else None
    review: ReviewSettings | None
    detail: str | None = None
    if operator_owned:
        review, source = run_start_review, "base_snapshot"
    elif not isinstance(pull, dict):
        review, source = run_start_review, "run_start_snapshot"
    else:
        base_sha = _event_base_sha(event)
        if base_sha:
            review, source, detail = await _base_review_settings(scm, owner, repo, base_sha)
        else:
            review, source, detail = None, "defaults", "the PR base commit is unknown"
    if detail and review is None:
        logger.warning("ignore_paths: review.ignorePaths dropped — {}", detail)
    return build_review_ignore(input_value=input_value, review=review, source=source, detail=detail)


async def list_pull_request_paths(
    scm: ScmProvider, owner: str, repo: str, pull_number: int
) -> list[str] | None:
    """Return every path a pull request changes, or ``None`` on any doubt.

    Rename and copy sources (``previous_filename``) are listed alongside the new name,
    so a file renamed into an ignored name still counts as in scope.

    ``None`` (a failed read, or the listing hit its page cap) means the caller cannot
    prove every file is ignored and must run the review.
    """
    from mergecraft.scm.pull_files import list_pull_files

    paths: list[str] = []
    try:
        listing = await list_pull_files(
            scm,
            owner,
            repo,
            pull_number,
            page_size=_FILES_PAGE_SIZE,
            max_pages=_FILES_MAX_PAGES,
        )
        for entry in listing.items:
            for key in ("filename", "previous_filename"):
                name = str(entry.get(key) or "").strip()
                if name:
                    paths.append(name)
        if not listing.incomplete:
            return list(dict.fromkeys(paths))
    except Exception as err:  # a failed listing proves nothing; the review runs
        logger.info("ignore_paths: PR #{} file listing failed: {}", pull_number, err)
    return None


def ignored_paths_section(paths: Sequence[str]) -> str:
    """Render the review-body section naming the files the reviewer never saw."""
    unique = list(dict.fromkeys(paths))
    shown = unique[:_SECTION_LIST_CAP]
    lines = [
        IGNORED_PATHS_HEADING,
        "",
        f"{len(unique)} changed file(s) matched `ignore_paths` / `review.ignorePaths` "
        "and were left out of the diff the reviewer saw:",
        "",
        *(f"- `{path}`" for path in shown),
    ]
    if len(unique) > len(shown):
        lines.append(f"- … and {len(unique) - len(shown)} more")
    return "\n".join(lines)


def merge_ignored_paths_into_review_body(body: str, paths: Sequence[str]) -> str:
    """Append :func:`ignored_paths_section` to ``body`` once; unchanged without paths."""
    if not paths or IGNORED_PATHS_HEADING in body:
        return body
    section = ignored_paths_section(paths)
    return f"{body.rstrip()}\n\n{section}" if body.strip() else section


__all__ = [
    "DEFAULT_IGNORE_PATHS",
    "IGNORED_PATHS_HEADING",
    "INPUT_ENV",
    "FilteredDiff",
    "ReviewIgnore",
    "build_review_ignore",
    "filter_diff",
    "glob_matches",
    "ignored_paths_section",
    "list_pull_request_paths",
    "merge_ignored_paths_into_review_body",
    "parse_ignore_paths",
    "rename_sources",
    "resolve_review_ignore",
]
