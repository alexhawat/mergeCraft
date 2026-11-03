"""Review path ignoring: keep changelogs, lockfiles and generated files out of the diff.

``ignore_paths`` (Action input) and ``review.ignorePaths`` (repo config) name globs whose
changed files the reviewer never sees. A built-in default set (changelogs, lockfiles,
generated and minified files) applies unless ``review.ignorePathDefaults: false``.

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
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.classify.generated_files import (
    FileKind,
    classify_path,
    finding_survives_generated_policy,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mergecraft.config.settings import ReviewSettings
    from mergecraft.scm.protocol import ScmProvider

DEFAULT_IGNORE_PATHS: Final[tuple[str, ...]] = (
    "**/CHANGELOG.md",
    "**/*.lock",
    "**/package-lock.json",
)
"""Default globs. ``**/*.lock`` covers ``uv.lock``, ``Cargo.lock``, ``poetry.lock`` and
``yarn.lock``; generated and minified files are matched by
:func:`mergecraft.classify.generated_files.classify_path` on top of these."""

IGNORED_PATHS_HEADING: Final[str] = "### Not reviewed (ignored by config)"
INPUT_ENV: Final[str] = "INPUT_IGNORE_PATHS"
_CONFIG_REL: Final[str] = ".mergecraft/config.yaml"
_MAX_CONFIG_BYTES: Final[int] = 1024 * 1024
_FILES_PAGE_SIZE: Final[int] = 100
_FILES_MAX_PAGES: Final[int] = 30
_SECTION_LIST_CAP: Final[int] = 50
_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[\n,]")
_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r'^diff --git (?:"a/(?P<qa>.+?)" "b/(?P<qb>.+)"|a/(?P<a>.+?) b/(?P<b>.+))$'
)


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


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if pattern.startswith("**", i):
            i += 2
            if i < n and pattern[i] == "/":
                i += 1
                parts.append("(?:.*/)?")
            else:
                parts.append(".*")
            continue
        if char == "*":
            parts.append("[^/]*")
        elif char == "?":
            parts.append("[^/]")
        elif char == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                parts.append(re.escape(char))
            else:
                body = pattern[i + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                parts.append(f"[{body}]")
                i = end
        else:
            parts.append(re.escape(char))
        i += 1
    return re.compile("".join(parts) + r"\Z")


def glob_matches(pattern: str, path: str) -> bool:
    """Return whether ``pattern`` matches the whole repository-relative ``path``.

    Examples:
        >>> glob_matches("**/*.lock", "uv.lock"), glob_matches("*.md", "docs/a.md")
        (True, False)
    """
    normalized = path.replace("\\", "/").removeprefix("./")
    try:
        return _glob_regex(pattern).match(normalized) is not None
    except re.error:
        return False


@dataclass(frozen=True, slots=True)
class ReviewIgnore:
    """The run's review path matcher.

    Attributes:
        patterns: Every glob in force (defaults first, then config, then the input).
        generated_defaults: Whether generated and minified files are ignored too.
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

        ``changed_paths`` lets the generated-file rule keep a generated output in scope
        when its generator config changed in the same pull request.
        """
        if any(glob_matches(pattern, path) for pattern in self.patterns):
            return True
        if not self.generated_defaults:
            return False
        if classify_path(path) not in {FileKind.GENERATED, FileKind.MINIFIED}:
            return False
        return not finding_survives_generated_policy(
            path, change={"changed_paths": list(changed_paths) or [path]}
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


def _section_path(header: str) -> str | None:
    match = _HEADER_RE.match(header.rstrip("\r\n"))
    if match is None:
        return None
    return match.group("qb") or match.group("b")


def _split_sections(diff_text: str) -> tuple[str, list[tuple[str | None, str]]]:
    lines = diff_text.splitlines(keepends=True)
    prefix: list[str] = []
    sections: list[tuple[str | None, list[str]]] = []
    for line in lines:
        if line.startswith("diff --git "):
            sections.append((_section_path(line), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            prefix.append(line)
    return "".join(prefix), [(path, "".join(body)) for path, body in sections]


def filter_diff(diff_text: str, ignore: ReviewIgnore | None) -> FilteredDiff:
    """Drop the file sections of ``diff_text`` whose post-image path is ignored.

    A section whose header cannot be parsed is kept: an unreadable header is never a
    reason to review less.
    """
    prefix, sections = _split_sections(str(diff_text))
    paths = [path for path, _ in sections if path is not None]
    if ignore is None or not ignore.active:
        return FilteredDiff(text=str(diff_text), kept_paths=paths)
    kept_parts: list[str] = [prefix]
    ignored: list[str] = []
    kept: list[str] = []
    for path, body in sections:
        if path is not None and ignore.is_ignored(path, changed_paths=paths):
            ignored.append(path)
            continue
        if path is not None:
            kept.append(path)
        kept_parts.append(body)
    return FilteredDiff(
        text="".join(kept_parts),
        ignored_paths=list(dict.fromkeys(ignored)),
        kept_paths=list(dict.fromkeys(kept)),
    )


def _http_status(err: BaseException) -> int | None:
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _review_settings_from_text(text: str) -> ReviewSettings:
    from mergecraft.analyzers.settings_pin import repo_settings_from_text

    return repo_settings_from_text(text).review


async def _base_review_settings(
    scm: ScmProvider, owner: str, repo: str, base_sha: str
) -> tuple[ReviewSettings | None, str, str | None]:
    """Read ``review`` settings from the base commit's config through the contents API."""
    from mergecraft.config.settings import ReviewSettings

    try:
        payload = await scm.get(
            f"/repos/{owner}/{repo}/contents/{_CONFIG_REL}", params={"ref": base_sha}
        )
    except Exception as err:  # an unreadable base config drops the YAML half, never the review
        if _http_status(err) == 404:
            return ReviewSettings(), "base_sha", f"the PR base has no {_CONFIG_REL}"
        return None, "defaults", f"the PR base config could not be read ({type(err).__name__})"
    if not isinstance(payload, dict) or payload.get("type") != "file":
        return None, "defaults", f"{_CONFIG_REL} at the PR base is not a regular file"
    if payload.get("encoding") != "base64":
        return None, "defaults", f"{_CONFIG_REL} at the PR base has no inline content"
    try:
        raw = base64.b64decode(str(payload.get("content") or ""))
        if len(raw) > _MAX_CONFIG_BYTES:
            return None, "defaults", f"{_CONFIG_REL} at the PR base is too large"
        return _review_settings_from_text(raw.decode("utf-8")), "base_sha", None
    except Exception as err:  # a malformed base config fails toward reviewing more
        return None, "defaults", f"{_CONFIG_REL} at the PR base is invalid ({err})"


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
    """Return every changed post-image path of a pull request, or ``None`` on any doubt.

    ``None`` (a failed read, or the listing hit its page cap) means the caller cannot
    prove every file is ignored and must run the review.
    """
    endpoint = f"/repos/{owner}/{repo}/pulls/{pull_number}/files"
    paths: list[str] = []
    try:
        for page in range(1, _FILES_MAX_PAGES + 1):
            batch = list(
                await scm.get(endpoint, params={"per_page": _FILES_PAGE_SIZE, "page": page}) or []
            )
            for entry in batch:
                name = str(entry.get("filename") or "").strip() if isinstance(entry, dict) else ""
                if name:
                    paths.append(name)
            if len(batch) < _FILES_PAGE_SIZE:
                return list(dict.fromkeys(paths))
    except Exception as err:  # a failed listing proves nothing; the review runs
        logger.info("ignore_paths: PR #{} file listing failed: {}", pull_number, err)
        return None
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
    "resolve_review_ignore",
]
