"""W1.2 — committed ``trust.selfReview`` flip contracts (lane D, greened W2)."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.ci.workflow_support import REPO_ROOT

_COMMITTED_CONFIG = REPO_ROOT / ".mergecraft" / "config.yaml"
_FORK_EVENT: dict = {"pull_request": {"head": {"repo": {"fork": True, "full_name": "fork/demo"}}}}
_SAME_REPO_EVENT: dict = {
    "pull_request": {"head": {"repo": {"fork": False, "full_name": "acme/demo"}}}
}


def _trust_config_yaml(level: str) -> str:
    return f'trust:\n  selfReview: "{level}"\n'


def _resolve_policy(**kwargs):
    from mergecraft.config.trust_policy import resolve_trust_policy

    return resolve_trust_policy(**kwargs)


def test_committed_config_has_self_review_full_quoted() -> None:
    """D6 — dogfood config must carry ``trust.selfReview: \"full\"`` (quoted)."""
    text = _COMMITTED_CONFIG.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    trust = loaded.get("trust")
    assert isinstance(trust, dict), "committed config must define trust.selfReview"
    assert trust.get("selfReview") == "full"
    assert 'selfReview: "full"' in text or "selfReview: 'full'" in text


def test_committed_config_resolves_execution_trusted_on_same_repo_prt() -> None:
    """Plan 13 — committed dogfood config must elevate execution and authority on same-repo PRT."""
    policy = _resolve_policy(
        event=_SAME_REPO_EVENT,
        config_root=REPO_ROOT,
        event_name="pull_request_target",
    )
    assert policy.level == "full"
    assert policy.execution_trust == "trusted"
    assert policy.authority_trust == "trusted"


def test_committed_config_fork_pr_stays_untrusted() -> None:
    """Fork floor — committed ``full`` must not grant trust on a fork head."""
    policy = _resolve_policy(
        event=_FORK_EVENT,
        config_root=REPO_ROOT,
        event_name="pull_request_target",
    )
    assert policy.level == "full"
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


def test_fork_pr_stays_untrusted_on_both_axes_with_analyzers(tmp_path: Path) -> None:
    """Plan 13 regression — fork heads never gain execution or authority trust."""
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(_trust_config_yaml("analyzers"), encoding="utf-8")

    policy = _resolve_policy(
        event=_FORK_EVENT,
        config_root=tmp_path,
        event_name="pull_request_target",
    )
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"
