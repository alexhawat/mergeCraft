"""Fix labels from the operator's side of the pull request only (#1056 part 5).

``review.fixLabels`` names the labels that make a pull request a fix, which then
needs a fail-then-pass receipt. A pull request's own ``.mergecraft/config.yaml``
must not be able to change that list: a fork could set ``fixLabels: []`` and
switch off label-based fix detection. So, as for ``review.ignorePaths``, the list
is read from the run-start snapshot on an operator-owned run
(``pull_request_target``, the base checkout), from the base commit through the
contents API on any other pull request run, and from the run-start tree when
there is no pull request at all. Any doubt about the base gives the defaults,
never the head's list.

Module: mergecraft.review_policy.fix_labels
Depends: mergecraft.ci.red_green, mergecraft.review_policy.ignore_paths

Exports:
    resolve_fix_labels: The run's ``review.fixLabels``, read from the operator's side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.ci.red_green import DEFAULT_FIX_LABELS
from mergecraft.review_policy.ignore_paths import _base_review_settings, _event_base_sha

if TYPE_CHECKING:
    from mergecraft.config.settings import ReviewSettings
    from mergecraft.scm.protocol import ScmProvider


async def resolve_fix_labels(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    event: dict[str, Any] | None,
    run_start_review: ReviewSettings,
    operator_owned: bool,
) -> tuple[str, ...]:
    """Resolve the run's fix labels from operator-side config only.

    Args:
        scm (ScmProvider): Provider used to read the base config on a non-operator-owned
            pull request run.
        owner (str): Repository owner.
        repo (str): Repository name.
        event (dict[str, Any] | None): The bound GitHub event; its
            ``pull_request.base.sha`` names the base commit.
        run_start_review (ReviewSettings): ``review`` settings from the run-start tree.
        operator_owned (bool): Whether the run-start tree is the base (``pull_request_target``).

    Returns:
        tuple[str, ...]: The configured labels; the defaults (``bug``, ``fix``) when the
        base config has no ``fixLabels``, cannot be read, or the base commit is unknown.
    """
    pull = event.get("pull_request") if isinstance(event, dict) else None
    if operator_owned or not isinstance(pull, dict):
        return tuple(run_start_review.fix_labels)
    base_sha = _event_base_sha(event)
    if not base_sha:
        logger.warning("fix_labels: the PR base commit is unknown — using the defaults")
        return DEFAULT_FIX_LABELS
    try:
        review, _source, detail = await _base_review_settings(scm, owner, repo, base_sha)
    except Exception as err:  # the reader is total; this keeps the run going regardless
        review, detail = None, f"the PR base config could not be read ({type(err).__name__})"
    if review is None:
        logger.warning("fix_labels: review.fixLabels from the PR base dropped — {}", detail)
        return DEFAULT_FIX_LABELS
    return tuple(review.fix_labels)


__all__ = ["resolve_fix_labels"]
