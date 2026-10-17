"""Pre-dispatch triage: read the pull request, decide the tier, never skip on doubt.

``mergecraft.classify.triage`` is the pure decision. This module is its I/O shell: it
reads the pull request's diff through the files API, the head-side text of any prose
file the prose recognizer must prove stays out of a code fence, and the checks that
passed on the head SHA — then asks the pure function.

Everything here fails toward spending *more*: a failed read, a truncated listing, a file
GitHub sent no patch for, or a config that is not the operator's base-side config all
decide ``full``. The gate may only skip when it is certain.

Exports:
    load_triage_inputs: Read one pull request's diff, head text and passed checks.
    decide_fast_path: Read and decide, or say why the answer is ``full``.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.classify.triage import TriageDecision, TriageInputs, triage_diff

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.config.settings import FastPathSettings
    from mergecraft.scm.protocol import ScmProvider

_FILES_PAGE_SIZE: Final[int] = 100
_FILES_MAX_PAGES: Final[int] = 30
# Head-side text is read only to prove a prose edit stays out of a code fence.
_PROSE_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown", ".txt")
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


async def _read_diff(
    scm: ScmProvider, owner: str, repo: str, pull_number: int
) -> tuple[str, list[str]]:
    """Build the unified diff from the files API; refuse a truncated or patchless read."""
    endpoint = f"/repos/{owner}/{repo}/pulls/{pull_number}/files"
    parts: list[str] = []
    paths: list[str] = []
    for page in range(1, _FILES_MAX_PAGES + 1):
        batch = list(
            await scm.get(endpoint, params={"per_page": _FILES_PAGE_SIZE, "page": page}) or []
        )
        for entry in batch:
            name = str(entry.get("filename") or "").strip()
            if not name:
                continue
            patch = entry.get("patch")
            if not patch and _line_changes(entry) > 0:
                msg = f"{name} has line changes but GitHub sent no patch for it"
                raise TriageUnavailableError(msg)
            paths.append(name)
            parts.append(f"diff --git a/{name} b/{name}\n")
            if patch:
                parts.append(f"{patch}\n")
        if len(batch) < _FILES_PAGE_SIZE:
            return "".join(parts), paths
    msg = f"the files listing was truncated at the {_FILES_MAX_PAGES}-page cap"
    raise TriageUnavailableError(msg)


async def _read_head_files(
    scm: ScmProvider, owner: str, repo: str, head_sha: str, paths: list[str]
) -> dict[str, str]:
    if not paths or len(paths) > _MAX_PROSE_FILES:
        return {}
    if not all(path.lower().endswith(_PROSE_SUFFIXES) for path in paths):
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


async def _passed_checks(scm: ScmProvider, owner: str, repo: str, head_sha: str) -> tuple[str, ...]:
    listing = await scm.list_check_runs_for_ref(owner, repo, head_sha)
    rows = getattr(listing, "items", None)
    if not isinstance(rows, list):
        msg = "the check-run listing had an unexpected shape"
        raise TriageUnavailableError(msg)
    return tuple(
        dict.fromkeys(
            str(row.get("name"))
            for row in rows
            if isinstance(row, dict) and row.get("name") and row.get("conclusion") == "success"
        )
    )


async def load_triage_inputs(
    scm: ScmProvider, owner: str, repo: str, pull_number: int, head_sha: str
) -> TriageInputs:
    """Read the diff, the head-side prose text and the passed checks for one pull request.

    Raises:
        TriageUnavailableError: The diff could not be read completely.
        Exception: Any transport error; :func:`decide_fast_path` turns it into ``full``.
    """
    diff_text, paths = await _read_diff(scm, owner, repo, pull_number)
    head_files = await _read_head_files(scm, owner, repo, head_sha, paths)
    passed = await _passed_checks(scm, owner, repo, head_sha)
    return TriageInputs(diff_text=diff_text, head_files=head_files, passed_checks=passed)


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
) -> TriageDecision:
    """Return the triage tier for a pull request, ``full`` whenever there is any doubt.

    ``operator_owned`` says the config was read from the base ref, which a fork cannot
    write. Head-side config can never opt a pull request out of review. ``loader``
    replaces :func:`load_triage_inputs` (the caller's module-level binding, so the
    read can be substituted in tests).
    """
    if not config.enabled:
        return TriageDecision(tier="full", recognizer=None, reason="review.fastPath is not enabled")
    if not operator_owned:
        logger.info(
            "fast path: review.fastPath is ignored — it is only honoured from the "
            "operator's base-side config (a pull_request_target run)"
        )
        return TriageDecision(
            tier="full",
            recognizer=None,
            reason="review.fastPath is only honoured from the operator's base-side config",
        )
    try:
        read = loader or load_triage_inputs
        inputs = await read(scm, owner, repo, pull_number, head_sha)
    except Exception as err:  # any read failure is a reason to review, never to skip
        logger.warning(
            "fast path: PR #{} could not be read, so it gets a full review: {}", pull_number, err
        )
        return TriageDecision(
            tier="full",
            recognizer=None,
            reason=f"the pull request could not be read completely ({type(err).__name__}: {err})",
        )
    decision = triage_diff(
        inputs.diff_text,
        config=config,
        head_files=inputs.head_files,
        passed_checks=inputs.passed_checks,
    )
    logger.info("fast path: PR #{} triaged {} ({})", pull_number, decision.tier, decision.reason)
    return decision


__all__ = ["TriageUnavailableError", "decide_fast_path", "load_triage_inputs"]
