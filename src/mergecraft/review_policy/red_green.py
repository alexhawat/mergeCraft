"""The fail-then-pass receipt declaration, from the operator's side only (#1056 part 5).

``ciEvidence.redGreen`` names the receipt artifact and the one workflow allowed to
upload it. On a ``pull_request`` run the run-start settings are the pull request's
head, so a fork could declare its own workflow and artifact and upload a "proven"
receipt. The declaration is therefore read as ``review.fixLabels`` is: the run-start
snapshot on an operator-owned run (``pull_request_target``, the base checkout), the
base commit's config through the contents API on any other pull request run, and the
run-start tree when there is no pull request at all. A base without the block, an
unreadable or invalid base config, or an unknown base commit declares nothing; the
head's block is never used. :func:`read_red_green_declaration` also says why a base
could not be read, so the run can tell "declares none" from "could not read it".

Module: mergecraft.review_policy.red_green
Depends: mergecraft.review_policy.ignore_paths

Exports:
    read_red_green_declaration: The declaration plus why the base could not be read, if so.
    resolve_red_green_declaration: The run's ``ciEvidence.redGreen``, from the operator's side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.review_policy.ignore_paths import _base_repo_settings, _event_base_sha

if TYPE_CHECKING:
    from mergecraft.config.settings import CiEvidenceSettings, RedGreenReceiptSettings
    from mergecraft.scm.protocol import ScmProvider


async def read_red_green_declaration(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    event: dict[str, Any] | None,
    run_start_ci_evidence: CiEvidenceSettings,
    operator_owned: bool,
) -> tuple[RedGreenReceiptSettings | None, str | None]:
    """Resolve the run's receipt declaration and say whether the base could be read.

    Args:
        scm (ScmProvider): Provider used to read the base config on a non-operator-owned
            pull request run.
        owner (str): Repository owner.
        repo (str): Repository name.
        event (dict[str, Any] | None): The bound GitHub event; its
            ``pull_request.base.sha`` names the base commit.
        run_start_ci_evidence (CiEvidenceSettings): ``ciEvidence`` from the run-start tree.
        operator_owned (bool): Whether the run-start tree is the base (``pull_request_target``).

    Returns:
        tuple[RedGreenReceiptSettings | None, str | None]: The base-side declaration (or
        ``None``), and the reason the base could not be read: ``None`` when it was read,
        including a base without a config file or without the block.
    """
    pull = event.get("pull_request") if isinstance(event, dict) else None
    if operator_owned or not isinstance(pull, dict):
        return run_start_ci_evidence.red_green, None
    base_sha = _event_base_sha(event)
    if not base_sha:
        logger.warning("red_green: the PR base commit is unknown — no receipt is declared")
        return None, "the PR base commit is unknown"
    try:
        settings, _source, detail = await _base_repo_settings(scm, owner, repo, base_sha)
    except Exception as err:  # the reader is total; this keeps the run going regardless
        settings, detail = None, f"the PR base config could not be read ({type(err).__name__})"
    if settings is None:
        logger.warning("red_green: ciEvidence.redGreen from the PR base dropped — {}", detail)
        return None, detail or "the PR base config could not be read"
    return settings.ci_evidence.red_green, None


async def resolve_red_green_declaration(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    event: dict[str, Any] | None,
    run_start_ci_evidence: CiEvidenceSettings,
    operator_owned: bool,
) -> RedGreenReceiptSettings | None:
    """Resolve the run's receipt declaration from operator-side config only.

    Args:
        scm (ScmProvider): Provider used to read the base config on a non-operator-owned
            pull request run.
        owner (str): Repository owner.
        repo (str): Repository name.
        event (dict[str, Any] | None): The bound GitHub event; its
            ``pull_request.base.sha`` names the base commit.
        run_start_ci_evidence (CiEvidenceSettings): ``ciEvidence`` from the run-start tree.
        operator_owned (bool): Whether the run-start tree is the base (``pull_request_target``).

    Returns:
        RedGreenReceiptSettings | None: The base-side declaration, or ``None`` when the
        base declares none, cannot be read or validated, or is unknown.
    """
    declaration, _unreadable = await read_red_green_declaration(
        scm,
        owner,
        repo,
        event=event,
        run_start_ci_evidence=run_start_ci_evidence,
        operator_owned=operator_owned,
    )
    return declaration


__all__ = ["read_red_green_declaration", "resolve_red_green_declaration"]
