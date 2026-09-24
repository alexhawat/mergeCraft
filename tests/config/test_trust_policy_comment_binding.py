"""S4 — an event that names a PR but carries no bound head is a fork (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

Locked contracts exercised here (test-plan ``docs/test-plans/trust-boundaries.md``):

* **TB-D1** — ``is_fork_pull_request`` returns True when ``pull_request`` is absent
  and ``issue.pull_request`` is present, or when a ``workflow_dispatch`` payload
  names a PR number. A comment on a plain issue and a dispatch that names no PR
  are unchanged.
* **TB-D2** — ``bind_target_pull_request(event, pull)`` is a pure function that
  returns a copy of the event with ``pull_request`` set from fetched metadata.
* **TB-D3** — one fork predicate serves the trust tier (``resolve_trust_policy``).

RED markers were reconciled after TB2 landed; every case here is a real pass.
A comment on a plain issue stays trusted today and must keep doing so — those
guards carry no marker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config.trust_policy import is_fork_pull_request, resolve_trust_policy

if TYPE_CHECKING:
    from pathlib import Path

_SAME_REPO = "acme/demo"
_FORK_REPO = "contributor/demo"


def _comment_on_pr_event(
    *,
    number: int = 7,
    association: str = "OWNER",
) -> dict[str, Any]:
    """An ``issue_comment`` payload on a PR: ``issue.pull_request``, no head."""
    return {
        "action": "created",
        "issue": {
            "number": number,
            "title": "A pull request",
            "pull_request": {
                "url": f"https://api.github.com/repos/{_SAME_REPO}/pulls/{number}",
                "html_url": f"https://github.com/{_SAME_REPO}/pull/{number}",
            },
        },
        "comment": {
            "author_association": association,
            "body": "@mergecraft review",
            "user": {"login": "maintainer"},
        },
        "repository": {"full_name": _SAME_REPO, "default_branch": "main"},
    }


def _comment_on_plain_issue_event(*, number: int = 9) -> dict[str, Any]:
    """An ``issue_comment`` payload on a plain issue — no PR anywhere."""
    return {
        "action": "created",
        "issue": {"number": number, "title": "An issue"},
        "comment": {
            "author_association": "OWNER",
            "body": "@mergecraft review",
            "user": {"login": "maintainer"},
        },
        "repository": {"full_name": _SAME_REPO, "default_branch": "main"},
    }


def _dispatch_event_naming_pr(number: int) -> dict[str, Any]:
    """A ``workflow_dispatch`` payload whose review input names a PR number.

    The composed dispatch prompt (``.github/workflows/mergecraft.yml``,
    "Compose review prompt") is the operator-visible review input for a
    dispatch run; it is the only place a dispatch names a PR.
    """
    return {
        "action": "workflow_dispatch",
        "inputs": {
            "prompt": (
                f"Review pull request #{number}. First call the mergecraft MCP tool "
                "mergecraft_checkout_pr."
            )
        },
        "ref": "refs/heads/feature",
        "repository": {"full_name": _SAME_REPO, "default_branch": "main"},
    }


def _dispatch_event_without_pr() -> dict[str, Any]:
    return {
        "action": "workflow_dispatch",
        "inputs": {"prompt": "Review the current pull request."},
        "ref": "refs/heads/main",
        "repository": {"full_name": _SAME_REPO, "default_branch": "main"},
    }


def _pull_metadata(*, number: int, repo: str, fork: bool, sha: str = "a" * 40) -> dict[str, Any]:
    return {
        "number": number,
        "head": {
            "ref": "feature",
            "sha": sha,
            "repo": {"full_name": repo, "fork": fork},
        },
        "base": {
            "ref": "main",
            "sha": "b" * 40,
            "repo": {"full_name": _SAME_REPO, "fork": False},
        },
        "title": "A pull request",
        "html_url": f"https://github.com/{_SAME_REPO}/pull/{number}",
    }


def _bind(event: dict[str, Any], pull: dict[str, Any]) -> dict[str, Any]:
    """Call the TB-D2 seam lazily so collection stays clean pre-implementation."""
    from mergecraft.config.trust_policy import bind_target_pull_request

    return bind_target_pull_request(event, pull)


# ── TB-D1: comment on a PR with no bound head is a fork ──────────────────────


def test_comment_on_pr_without_pull_request_is_a_fork() -> None:
    """TB-D1 — ``issue.pull_request`` present and no top-level ``pull_request``."""
    event = _comment_on_pr_event()
    assert is_fork_pull_request(event) is True


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_comment_on_pr_is_a_fork_regardless_of_commenter(association: str) -> None:
    """The floor is about the code under review, never who commented."""
    event = _comment_on_pr_event(association=association)
    assert is_fork_pull_request(event) is True


def test_comment_on_plain_issue_is_not_a_fork() -> None:
    """Guard — a comment on a plain issue has no PR to floor."""
    assert is_fork_pull_request(_comment_on_plain_issue_event()) is False


def test_dispatch_naming_a_pr_is_a_fork_until_bound() -> None:
    """TB-D1 — a dispatch that names a PR carries no bound head yet."""
    assert is_fork_pull_request(_dispatch_event_naming_pr(42)) is True


def test_dispatch_without_a_pr_is_not_a_fork() -> None:
    """Guard — a dispatch that names no PR is unchanged."""
    assert is_fork_pull_request(_dispatch_event_without_pr()) is False


# ── TB-D2: bind by fetching, once ────────────────────────────────────────────


def test_bind_target_pull_request_is_pure_and_sets_the_bound_head() -> None:
    """TB-D2 — ``bind_target_pull_request`` returns a copy, original untouched."""
    event = _comment_on_pr_event(number=7)
    pull = _pull_metadata(number=7, repo=_SAME_REPO, fork=False)

    bound = _bind(event, pull)

    assert bound is not event
    assert "pull_request" not in event, "binding must not mutate the input event"
    pr = bound["pull_request"]
    assert pr["number"] == 7
    assert pr["head"]["sha"] == "a" * 40
    assert pr["head"]["repo"]["full_name"] == _SAME_REPO
    assert pr["base"]["repo"]["full_name"] == _SAME_REPO


def test_binding_a_same_repo_pr_clears_the_fork_floor() -> None:
    """TB-D2 — once the same-repo head is bound, the event is not a fork."""
    bound = _bind(
        _comment_on_pr_event(number=7),
        _pull_metadata(number=7, repo=_SAME_REPO, fork=False),
    )
    assert is_fork_pull_request(bound) is False


def test_binding_a_fork_pr_keeps_the_fork_floor() -> None:
    """TB-D2 — binding a fork confirms the floor rather than lifting it."""
    bound = _bind(
        _comment_on_pr_event(number=7),
        _pull_metadata(number=7, repo=_FORK_REPO, fork=True),
    )
    assert is_fork_pull_request(bound) is True


# ── TB-D1/D3: resolve_trust_policy applies the one fork predicate ────────────


def test_comment_on_pr_resolves_untrusted_both_axes(tmp_path: Path) -> None:
    """TB-D1/D3 — an unbound comment-on-PR floors both trust axes."""
    policy = resolve_trust_policy(
        event=_comment_on_pr_event(),
        config_root=tmp_path,
        event_name="issue_comment",
    )
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


def test_comment_after_binding_same_repo_is_trusted(tmp_path: Path) -> None:
    """TB-D2/D3 — a maintainer comment on a same-repo PR stays trusted once bound."""
    bound = _bind(
        _comment_on_pr_event(),
        _pull_metadata(number=7, repo=_SAME_REPO, fork=False),
    )
    policy = resolve_trust_policy(
        event=bound,
        config_root=tmp_path,
        event_name="issue_comment",
    )
    assert policy.execution_trust == "trusted"
    assert policy.authority_trust == "trusted"


def test_comment_after_binding_a_fork_is_untrusted(tmp_path: Path) -> None:
    """TB-D2/D3 — binding a fork keeps the floor on a maintainer comment."""
    bound = _bind(
        _comment_on_pr_event(),
        _pull_metadata(number=7, repo=_FORK_REPO, fork=True),
    )
    policy = resolve_trust_policy(
        event=bound,
        config_root=tmp_path,
        event_name="issue_comment",
    )
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


def test_comment_on_plain_issue_stays_trusted(tmp_path: Path) -> None:
    """Guard — a maintainer comment on a plain issue is unchanged (trusted)."""
    policy = resolve_trust_policy(
        event=_comment_on_plain_issue_event(),
        config_root=tmp_path,
        event_name="issue_comment",
    )
    assert policy.execution_trust == "trusted"
    assert policy.authority_trust == "trusted"


def test_dispatch_naming_a_pr_resolves_untrusted_before_binding(tmp_path: Path) -> None:
    """TB-D1 — a dispatch that names a PR but has no bound head is floored."""
    policy = resolve_trust_policy(
        event=_dispatch_event_naming_pr(42),
        config_root=tmp_path,
        event_name="workflow_dispatch",
    )
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


def test_dispatch_after_binding_same_repo_is_trusted(tmp_path: Path) -> None:
    """TB-D2 — a dispatch naming a same-repo PR is trusted once bound."""
    bound = _bind(
        _dispatch_event_naming_pr(42),
        _pull_metadata(number=42, repo=_SAME_REPO, fork=False),
    )
    policy = resolve_trust_policy(
        event=bound,
        config_root=tmp_path,
        event_name="workflow_dispatch",
    )
    assert policy.execution_trust == "trusted"


def test_dispatch_after_binding_a_fork_is_untrusted(tmp_path: Path) -> None:
    """TB-D2 — a dispatch naming a fork PR is floored once bound."""
    bound = _bind(
        _dispatch_event_naming_pr(42),
        _pull_metadata(number=42, repo=_FORK_REPO, fork=True),
    )
    policy = resolve_trust_policy(
        event=bound,
        config_root=tmp_path,
        event_name="workflow_dispatch",
    )
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


def test_dispatch_without_a_pr_stays_trusted(tmp_path: Path) -> None:
    """Guard — a dispatch naming no PR is unchanged (trusted)."""
    policy = resolve_trust_policy(
        event=_dispatch_event_without_pr(),
        config_root=tmp_path,
        event_name="workflow_dispatch",
    )
    assert policy.execution_trust == "trusted"
