"""Pre-dispatch triage: read the pull request, decide the tier, never skip on doubt.

``mergecraft.classify.triage`` is the pure decision. This module is its I/O shell: it
reads the pull request's diff through the files API, the head-side text of any prose
file needed to prove prose, comments or whitespace stay outside executable content,
and the checks that passed on the head SHA — then asks the pure function.

Everything here fails toward spending *more*: a failed read, a truncated listing, a file
GitHub sent no patch for, or a config that is not the operator's base-side config all
decide ``full``. The gate may only skip when it is certain — a pin-bump skip also needs
the verifying check to belong to a GitHub App the operator named in
``pinBump.trustedCheckApps``, because a check-run name alone is whoever set it.

Exports:
    load_triage_inputs: Read one pull request's diff, head text and passed checks.
    triage_pull_request: Read and decide, returning the inputs the decision saw.
    decide_fast_path: Read and decide, or say why the answer is ``full``.
"""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.classify.generated_files import FileKind, classify_path
from mergecraft.classify.triage import (
    COMMENT_ONLY_SUFFIXES,
    TriageDecision,
    TriageInputs,
    triage_diff,
    trusted_check_apps,
)
from mergecraft.scm.pull_files import list_pull_files

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection

    from mergecraft.config.settings import FastPathSettings
    from mergecraft.scm.protocol import ScmProvider

_FILES_PAGE_SIZE: Final[int] = 100
_FILES_MAX_PAGES: Final[int] = 30
# Head-side text is read only to prove a prose edit stays out of a code fence, or a
# comment-only/whitespace edit stays out of a string literal or a block comment.
_PROSE_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown", ".txt")
_HEAD_TEXT_SUFFIXES: Final[tuple[str, ...]] = (
    *_PROSE_SUFFIXES,
    *COMMENT_ONLY_SUFFIXES,
    ".py",
    ".js",
)
_MAX_PROSE_FILES: Final[int] = 25
_MAX_HEAD_CHARS: Final[int] = 512_000


class TriageUnavailableError(Exception):
    """The pull request could not be read completely, so it cannot be triaged."""


def _line_changes(entry: dict[str, Any]) -> int:
    total = 0
    for key in ("additions", "deletions"):
        try:
            total += int(entry.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _previous_filename(entry: dict[str, Any], name: str) -> str:
    """The pre-image path of a renamed or copied entry, or ``""`` for an in-place edit."""
    previous = str(entry.get("previous_filename") or "").strip()
    return previous if previous and previous != name else ""


def _section_header(entry: dict[str, Any], name: str) -> str:
    """The ``diff --git`` header for one files-API entry.

    GitHub reports a rename or copy as ``previous_filename`` on the entry rather
    than in the patch, so the header is rebuilt the way ``git diff`` writes it:
    ``a/<previous> b/<name>`` plus the ``rename from`` / ``rename to`` (or
    ``copy from`` / ``copy to``) lines. Without them the pre-image is invisible to
    every reader of this diff and a rename looks like an in-place edit.
    """
    previous = _previous_filename(entry, name)
    if not previous:
        return f"diff --git a/{name} b/{name}\n"
    verb = "copy" if str(entry.get("status") or "").strip().lower() == "copied" else "rename"
    return f"diff --git a/{previous} b/{name}\n{verb} from {previous}\n{verb} to {name}\n"


async def _read_diff(
    scm: ScmProvider, owner: str, repo: str, pull_number: int, *, head_sha: str | None = None
) -> tuple[str, list[str]]:
    """Build the unified diff from the files API; refuse a truncated or patchless read."""
    listing = await list_pull_files(
        scm,
        owner,
        repo,
        pull_number,
        head_sha=head_sha,
        page_size=_FILES_PAGE_SIZE,
        max_pages=_FILES_MAX_PAGES,
    )
    parts: list[str] = []
    paths: list[str] = []
    for entry in listing.items:
        name = str(entry.get("filename") or "").strip()
        if not name:
            continue
        patch = entry.get("patch")
        if not patch and _line_changes(entry) > 0:
            msg = f"{name} has line changes but GitHub sent no patch for it"
            raise TriageUnavailableError(msg)
        paths.append(name)
        parts.append(_section_header(entry, name))
        if patch:
            parts.append(f"{patch}\n")
        # Include the source in _read_head_files' all-prose suffix gate.
        # Recognizers read both names from the rebuilt diff header above.
        previous = _previous_filename(entry, name)
        if previous:
            paths.append(previous)
    if not listing.incomplete:
        return "".join(parts), list(dict.fromkeys(paths))
    msg = f"the files listing was truncated at the {_FILES_MAX_PAGES}-page cap"
    raise TriageUnavailableError(msg)


async def _read_head_files(
    scm: ScmProvider,
    owner: str,
    repo: str,
    head_sha: str,
    paths: list[str],
    *,
    read_code_head: bool = False,
    any_suffix: bool = False,
) -> dict[str, str]:
    if not paths or len(paths) > _MAX_PROSE_FILES:
        return {}
    suffixes = _HEAD_TEXT_SUFFIXES if read_code_head else _PROSE_SUFFIXES
    if not any_suffix and not all(path.lower().endswith(suffixes) for path in paths):
        return {}
    texts: dict[str, str] = {}
    for path in paths:
        try:
            payload = await scm.get(
                f"/repos/{owner}/{repo}/contents/{path}", params={"ref": head_sha}
            )
            if not isinstance(payload, dict) or payload.get("encoding") != "base64":
                continue
            text = base64.b64decode(str(payload.get("content") or "")).decode("utf-8")
        except Exception as err:  # unreadable head text proves nothing; the file stays unproven
            logger.info("fast path: head text of {} unreadable: {}", path, err)
            continue
        if len(text) <= _MAX_HEAD_CHARS:
            texts[path] = text
    return texts


async def _passed_checks(
    scm: ScmProvider,
    owner: str,
    repo: str,
    head_sha: str,
    *,
    trusted_apps: Collection[str],
) -> tuple[str, ...]:
    """Names of the successful head-SHA checks whose run belongs to a trusted App.

    A check-run name and conclusion are chosen by the run's creator, so a matching name
    proves nothing on its own. Only a run published by one of the operator's trusted
    GitHub Apps counts; an absent or untrusted ``app.slug`` is skipped, and with no
    trusted App this reads nothing at all.
    """
    trusted = trusted_check_apps(trusted_apps)
    if not trusted:
        return ()
    listing = await scm.list_check_runs_for_ref(owner, repo, head_sha)
    rows = getattr(listing, "items", None)
    if not isinstance(rows, list):
        msg = "the check-run listing had an unexpected shape"
        raise TriageUnavailableError(msg)
    return tuple(
        dict.fromkeys(
            str(row.get("name"))
            for row in rows
            if isinstance(row, dict)
            and row.get("name")
            and row.get("conclusion") == "success"
            and _check_app_slug(row) in trusted
        )
    )


def _check_app_slug(row: dict[str, Any]) -> str:
    app = row.get("app")
    if not isinstance(app, dict):
        return ""
    slug = app.get("slug")
    return slug.strip().lower() if isinstance(slug, str) else ""


async def _verify_file_modes(
    scm: ScmProvider, owner: str, repo: str, pull_number: int, head_sha: str, paths: list[str]
) -> None:
    """Files-API patches omit mode changes; compare only the immutable directories containing changed files."""
    root = f"/repos/{owner}/{repo}"
    pull = await scm.get(f"{root}/pulls/{pull_number}")
    if not isinstance(pull, dict):
        raise TriageUnavailableError("missing pull request metadata for file-mode proof")
    base, head = pull.get("base"), pull.get("head")
    base_sha = base.get("sha") if isinstance(base, dict) else None
    if (
        not isinstance(base_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", base_sha) is None
        or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None
        or not isinstance(head, dict)
        or head.get("sha") != head_sha
    ):
        raise TriageUnavailableError("pull request SHA mismatch in file-mode proof")
    trees: dict[str, dict[str, dict[str, Any]]] = {}

    async def entries(sha: str) -> dict[str, dict[str, Any]]:
        """Read each immutable directory once; never request a repository-wide tree."""
        if sha not in trees:
            if len(trees) >= 128:
                raise TriageUnavailableError("file-mode proof exceeds directory budget")
            tree = await scm.get(f"{root}/git/trees/{sha}")
            if not isinstance(tree, dict) or tree.get("truncated") is not False:
                raise TriageUnavailableError("missing or truncated tree in file-mode proof")
            rows = tree.get("tree")
            if not isinstance(rows, list):
                raise TriageUnavailableError("invalid tree in file-mode proof")
            indexed: dict[str, dict[str, Any]] = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                    raise TriageUnavailableError("invalid directory entry in file-mode proof")
                name = row["path"]
                if name in indexed:
                    raise TriageUnavailableError("duplicate directory entry in file-mode proof")
                indexed[name] = row
            trees[sha] = indexed
        return trees[sha]

    modes: list[dict[str, str]] = []
    for revision in (base_sha, head_sha):
        matched: dict[str, str] = {}
        for path in set(paths):
            parts = path.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise TriageUnavailableError("invalid path in file-mode proof")
            sha = revision
            for directory in parts[:-1]:
                row = (await entries(sha)).get(directory, {})
                child = row.get("sha")
                if (
                    row.get("type") != "tree"
                    or row.get("mode") != "040000"
                    or not isinstance(child, str)
                    or re.fullmatch(r"[0-9a-f]{40}", child) is None
                ):
                    raise TriageUnavailableError("unproven parent directory in file-mode proof")
                sha = child
            row = (await entries(sha)).get(parts[-1], {})
            mode = row.get("mode")
            if mode not in {"100644", "100755"} or row.get("type") != "blob":
                raise TriageUnavailableError("unproven regular-file mode")
            matched[path] = mode
        modes.append(matched)
    if modes[0] != modes[1]:
        raise TriageUnavailableError("file modes changed with whitespace")


async def load_triage_inputs(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    head_sha: str,
    *,
    trusted_apps: Collection[str] = (),
    read_code_head: bool = False,
    read_generated_head: bool = False,
) -> TriageInputs:
    """Read the diff, the head-side prose/comment text and the trusted Apps' passed checks.

    ``trusted_apps`` is the operator's ``pinBump.trustedCheckApps``: a check run
    only counts when its ``app.slug`` is in it. ``read_code_head`` also reads the head
    text needed by comment-only and whitespace proofs. The caller sets it when either
    recognizer is opted in or ``lite`` is enabled. ``read_generated_head`` also reads
    the head text of every ``generated/`` path, whatever its suffix, so the
    ``generated`` recognizer can check it for a generated-file marker. The caller
    verifies file modes after classification and before acting on a whitespace match.

    Raises:
        TriageUnavailableError: The diff could not be read completely.
        Exception: Any transport error; :func:`decide_fast_path` turns it into ``full``.
    """
    diff_text, paths = await _read_diff(scm, owner, repo, pull_number, head_sha=head_sha)
    head_files = await _read_head_files(
        scm, owner, repo, head_sha, paths, read_code_head=read_code_head
    )
    if read_generated_head:
        generated = [
            path
            for path in paths
            if path not in head_files and classify_path(path) == FileKind.GENERATED
        ]
        head_files.update(
            await _read_head_files(scm, owner, repo, head_sha, generated, any_suffix=True)
        )
    passed = await _passed_checks(scm, owner, repo, head_sha, trusted_apps=trusted_apps)
    return TriageInputs(
        diff_text=diff_text,
        head_files=head_files,
        passed_checks=passed,
    )


async def triage_pull_request(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    head_sha: str,
    *,
    config: FastPathSettings,
    operator_owned: bool,
    loader: Callable[..., Awaitable[TriageInputs]] | None = None,
    instruction_extra_filenames: Collection[str] = (),
) -> tuple[TriageDecision, TriageInputs | None]:
    """Return the triage tier and the inputs it was decided from.

    The inputs are ``None`` whenever the pull request was not read (fast path off,
    config not the operator's, or a failed read), so a caller that acts on the diff
    (the ``lite`` driver) only ever sees the exact text the decision saw.
    ``operator_owned`` says the config was read from the base ref, which a fork cannot
    write. Head-side config can never opt a pull request out of review. ``loader``
    replaces :func:`load_triage_inputs` (the caller's module-level binding, so the
    read can be substituted in tests). ``instruction_extra_filenames`` is the
    operator's ``review.instructionExtraFilenames``, which are never prose.
    """
    if not config.enabled:
        return (
            TriageDecision(tier="full", recognizer=None, reason="review.fastPath is not enabled"),
            None,
        )
    if not operator_owned:
        logger.info(
            "fast path: review.fastPath is ignored — it is only honoured from the "
            "operator's base-side config (a pull_request_target run)"
        )
        return (
            TriageDecision(
                tier="full",
                recognizer=None,
                reason="review.fastPath is only honoured from the operator's base-side config",
            ),
            None,
        )
    try:
        read = loader or load_triage_inputs
        inputs = await read(
            scm,
            owner,
            repo,
            pull_number,
            head_sha,
            trusted_apps=config.pin_bump.trusted_check_apps,
            read_code_head=bool({"commentOnly", "whitespace"} & set(config.skip_llm))
            or config.lite.enabled,
            read_generated_head="generated" in config.skip_llm or config.lite.enabled,
        )
        decision = triage_diff(
            inputs.diff_text,
            config=config,
            head_files=inputs.head_files,
            passed_checks=inputs.passed_checks,
            instruction_extra_filenames=instruction_extra_filenames,
        )
        if decision.recognizer == "whitespace" and decision.tier != "full":
            from mergecraft.utils.diff_paths import changed_paths_from_diff

            # Recognize once, then prove the omitted file modes before spending
            # less. Both skip and lite decisions require the same proof.
            await _verify_file_modes(
                scm,
                owner,
                repo,
                pull_number,
                head_sha,
                changed_paths_from_diff(inputs.diff_text),
            )
    except Exception as err:  # any read failure is a reason to review, never to skip
        logger.warning(
            "fast path: PR #{} could not be read, so it gets a full review: {}", pull_number, err
        )
        return (
            TriageDecision(
                tier="full",
                recognizer=None,
                reason=(
                    f"the pull request could not be read completely ({type(err).__name__}: {err})"
                ),
            ),
            None,
        )
    logger.info("fast path: PR #{} triaged {} ({})", pull_number, decision.tier, decision.reason)
    return decision, inputs


async def decide_fast_path(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    head_sha: str,
    *,
    config: FastPathSettings,
    operator_owned: bool,
    loader: Callable[..., Awaitable[TriageInputs]] | None = None,
    instruction_extra_filenames: Collection[str] = (),
) -> TriageDecision:
    """Return the triage tier for a pull request, ``full`` whenever there is any doubt.

    The decision half of :func:`triage_pull_request`.
    """
    decision, _inputs = await triage_pull_request(
        scm,
        owner,
        repo,
        pull_number,
        head_sha,
        config=config,
        operator_owned=operator_owned,
        loader=loader,
        instruction_extra_filenames=instruction_extra_filenames,
    )
    return decision


__all__ = [
    "TriageUnavailableError",
    "decide_fast_path",
    "load_triage_inputs",
    "triage_pull_request",
]
