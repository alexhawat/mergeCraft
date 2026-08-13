"""PR S4 — fail-closed default for ``derive_trust_tier`` (#144).

The third fail-open default in ``analyzers/trust.py`` sits at the bottom of
:func:`mergecraft.analyzers.trust.derive_trust_tier`: today every event shape
that does not match a recognised branch falls through to ``"trusted"`` —
including the empty event, an unrecognised ``GITHUB_EVENT_NAME``, and a
malformed payload missing the keys the recognised branches read.

This suite pins the **post-flip** contract: the fall-through resolves to
``"untrusted"`` in every case the prior default silently trusted. The PR-shaped
``pull_request`` branch is gated on ``GITHUB_EVENT_NAME == "pull_request"`` and
only a same-repo shape (``fork is False``) earns the trusted tier; unknown
event names, and ``pull_request`` payloads with missing or wrong-typed nested
fields, all fail closed to ``"untrusted"``. The regression pins keep the
recognised branches locked down so the flip cannot move them by accident. The
caller-tolerance test enumerates the single production call site (``main.py``'s
``derive_trust_tier``) and asserts the downstream helpers consume the untrusted
result without raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    build_analyzer_env,
    derive_trust_tier,
    evaluate_manifest_for_tier,
    resolve_selection_tier,
)
from tests.analyzers.support import (
    FORK_PULL_REQUEST_EVENT,
    SAME_REPO_PULL_REQUEST_EVENT,
    import_module,
)

if TYPE_CHECKING:
    import pytest


def test_unknown_event_name_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — an unrecognised ``GITHUB_EVENT_NAME`` resolves to ``"untrusted"``.

    None of the recognised branches (``workflow_dispatch``, ``pull_request_target``,
    the ``pull_request`` dict shape) match an arbitrary event name. Under the
    post-flip contract the fall-through returns ``"untrusted"``.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "totally_unrecognised_event")
    tier = derive_trust_tier(event={"some": "payload"})
    assert tier == "untrusted"


def test_malformed_payload_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — a payload missing the keys the recognised branches read resolves
    to ``"untrusted"`` without raising.

    The fall-through must not crash on a payload with no ``pull_request`` key
    and no other recognised shape, and must not silently upgrade to trusted.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event={"unrelated": "shape"})
    assert tier == "untrusted"


def test_empty_event_name_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — ``GITHUB_EVENT_NAME`` unset or empty resolves to ``"untrusted"``.

    An Action without ``GITHUB_EVENT_NAME`` set (or with it cleared) used to
    fall through to ``"trusted"`` once the ``event`` dict was non-empty;
    after S4.2 the same input resolves to ``"untrusted"``.
    """
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    tier = derive_trust_tier(event={"some": "payload"})
    assert tier == "untrusted"


def test_unknown_event_name_with_pr_shaped_payload_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — an unrecognised event name with a PR-shaped payload stays untrusted.

    The P1 regression: the ``pull_request`` dict branch is gated on
    ``GITHUB_EVENT_NAME == "pull_request"``, so an arbitrary event name cannot
    reach the same-repo ``"trusted"`` return by smuggling a PR-shaped payload.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "totally_unrecognised_event")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": {"fork": False}}}})
    assert tier == "untrusted"


def test_pull_request_empty_dict_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — ``pull_request`` with an empty dict resolves to ``"untrusted"``.

    The P1 regression: a ``pull_request`` whose ``head`` is missing used to
    fall out of the nested lookups and hit the permissive ``return "trusted"``.
    Only ``fork is False`` earns the trusted tier now.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event={"pull_request": {}})
    assert tier == "untrusted"


def test_pull_request_missing_head_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — ``pull_request`` with a non-dict ``head`` resolves to ``"untrusted"``."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event={"pull_request": {"head": "not-a-dict"}})
    assert tier == "untrusted"


def test_pull_request_missing_repo_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — ``pull_request.head`` with a non-dict ``repo`` resolves to ``"untrusted"``."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": "not-a-dict"}}})
    assert tier == "untrusted"


def test_pull_request_missing_fork_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — ``pull_request.head.repo`` without ``fork`` resolves to ``"untrusted"``.

    The P1 regression: a missing ``fork`` key used to fall through to the
    permissive ``return "trusted"``; only an explicit ``fork is False``
    (same-repo) earns the trusted tier.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": {}}}})
    assert tier == "untrusted"


def test_pull_request_wrong_typed_fork_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — a wrong-typed ``fork`` value resolves to ``"untrusted"``.

    ``fork`` is compared with ``is False``, so a truthy or non-boolean value
    cannot accidentally land on the same-repo trusted branch.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": {"fork": "false"}}}})
    assert tier == "untrusted"


def test_workflow_dispatch_remains_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 regression pin — ``workflow_dispatch`` keeps the trusted tier.

    The flip must not move the explicit ``workflow_dispatch`` branch.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    tier = derive_trust_tier(event={"action": "workflow_dispatch"})
    assert tier == "trusted"


def test_pull_request_target_tier_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 regression pin — ``pull_request_target`` keeps the untrusted tier.

    The flip must not move the explicit ``pull_request_target`` branch.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": {"fork": False}}}})
    assert tier == "untrusted"


def test_fork_head_pull_request_remains_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 regression pin — fork-head ``pull_request`` keeps the untrusted tier.

    The flip must not move the fork detection branch — a fork PR is the
    canonical untrusted shape and must not be silently promoted.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event=FORK_PULL_REQUEST_EVENT)
    assert tier == "untrusted"


def test_same_repo_pull_request_tier_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 regression pin — same-repo ``pull_request`` keeps the trusted tier.

    The branch most at risk of collateral damage from the fall-through flip:
    a same-repo PR with a dict-shaped ``pull_request`` resolves to
    ``"trusted"`` via the explicit dict branch, *not* via the fall-through.
    This pin guards against a refactor that loses the dict branch on the way
    to changing the fall-through default.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event=SAME_REPO_PULL_REQUEST_EVENT)
    assert tier == "trusted"


def test_every_caller_tolerates_untrusted_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4.1 — the production caller chain tolerates the post-flip untrusted
    default rather than crashing.

    Per the S4.2 caller audit, the single production call site is
    ``src/mergecraft/main.py`` (``trust_tier = derive_trust_tier(event=...)``);
    that return value gates ``setup_script`` execution (``main.py:368``), the
    analyzer env builder, the manifest tier gate, the command-overrides gate,
    and the selection-tier resolver. For an unrecognised event shape all of
    these must consume the untrusted result without raising and without
    expanding what the run is allowed to see.

    This test does not import ``main.py`` (its full flow is covered by
    ``test_trust_ordering.py``); it exercises the downstream helpers directly
    with the untrusted result, and asserts both the tier returned by
    ``derive_trust_tier`` and that every helper handles it cleanly.
    """
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml").read_text(
        encoding="utf-8"
    )
    trusted_only_manifest = manifest_mod.load_manifest_yaml(
        raw.replace("trust: untrusted", "trust: trusted")
    )

    monkeypatch.setenv("GITHUB_EVENT_NAME", "totally_unrecognised_event")
    tier = derive_trust_tier(event={"some": "payload"})
    assert tier == "untrusted"

    # Analyzer env builder must scrub secrets on the untrusted tier
    # (build_analyzer_env is a pure function: it returns a dict, never raises
    # on the untrusted branch).
    env = build_analyzer_env(event={"some": "payload"}, tier=tier, repo_env={})
    assert isinstance(env, dict)
    assert "GITHUB_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env

    # Manifest tier gate must produce a deterministic decision on untrusted,
    # not raise.
    decision = evaluate_manifest_for_tier(manifest=trusted_only_manifest, tier=tier)
    assert decision.skipped is True
    assert decision.reason is not None

    # Command-overrides gate must refuse on untrusted (never raise).
    assert allow_repo_command_overrides(tier) is False

    # Selection-tier resolver must stay at-or-stricter-than the derived tier
    # on untrusted, regardless of the requested mode (never raise).
    assert resolve_selection_tier(mode="auto", tier=tier) == "untrusted"
    assert resolve_selection_tier(mode="full", tier=tier) == "untrusted"
    assert resolve_selection_tier(mode="untrusted-only", tier=tier) == "untrusted"
