"""WB-T RED contract for the #42/#48 blast-radius classifier.

The classifier is intentionally imported inside each test. W6 owns the
production module; until it lands, these strict=False xfails collect and report
as expected failures rather than making the suite uncollectable.

Locked surface:

- ``classify_blast_radius(change: ChangeSet, *, rule_set: RuleSet | None =
  None) -> BlastRadiusClassification``
- ``BlastRadiusClassification`` exposes ``lane``, ``reason``, ``next_action``,
  and named ``categories``.
- ``RepoSettings.blast_radius_override`` supplies an additive per-repository
  rule override (D9).
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def classifier_api() -> Any:
    """Load the W6 API lazily so the RED suite remains collectable."""
    from importlib import import_module

    return import_module("mergecraft.classify.blast_radius")


def _change(*paths: str, **signals: object) -> dict[str, object]:
    """Build a side-effect-free change payload for the classifier contract."""
    return {"changed_paths": list(paths), "diff_stats": signals}


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
def test_classifier_low_risk_examples(classifier_api: Any) -> None:
    """Docs-only, tests-only, and small isolated changes enter the low lane."""
    classify = classifier_api.classify_blast_radius
    cases = (
        _change("docs/guide.md", files_changed=1, lines_added=8, lines_deleted=2),
        _change("tests/unit/test_widget.py", files_changed=1, lines_added=12, lines_deleted=4),
        _change("src/mergecraft/utils/time.py", files_changed=1, lines_added=3, lines_deleted=2),
    )
    for change in cases:
        result = classify(change)
        assert result.lane == "low"
        assert result.auto_merge_lane == "eligible"


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
def test_classifier_medium_risk_examples(classifier_api: Any) -> None:
    """Broad but reversible application changes require assisted review."""
    classify = classifier_api.classify_blast_radius
    cases = (
        _change("src/mergecraft/cli/app.py", "tests/cli/test_app.py", files_changed=2),
        _change("src/mergecraft/analyzers/pipeline.py", files_changed=1, lines_added=75),
        _change("src/mergecraft/config/settings.py", "docs/config.md", files_changed=2),
    )
    for change in cases:
        result = classify(change)
        assert result.lane == "medium"
        assert result.auto_merge_lane in {"assisted", "human_review"}


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("migrations/20260809_add_index.sql", "migrations"),
        ("src/auth/session.py", "auth"),
        ("src/security/tokens.py", "security"),
        ("src/payments/checkout.py", "payment"),
        (".github/workflows/deploy.yml", "deployment"),
        ("infra/terraform/network.tf", "irreversible_infra"),
        ("src/permissions/policy.py", "permissions"),
        ("config/production.yaml", "secrets_config"),
    ],
)
def test_classifier_high_risk_examples(classifier_api: Any, path: str, category: str) -> None:
    """#48 high-risk acceptance categories forbid automatic merging."""
    result = classifier_api.classify_blast_radius(_change(path, files_changed=1))
    assert result.lane == "high"
    assert result.auto_merge_lane == "forbidden"
    assert category in result.categories


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("db/migrations/001_init.sql", "migrations"),
        ("src/auth/login.py", "auth_security_payment"),
        ("src/security/headers.py", "auth_security_payment"),
        ("src/payment/refunds.py", "auth_security_payment"),
        (".env.example", "secrets_config_deployment"),
        ("config/runtime.yaml", "secrets_config_deployment"),
        (".github/workflows/test.yml", "secrets_config_deployment"),
        ("src/generated/schema.py", "generated_files"),
        ("src/mergecraft/__init__.py", "public_api_changes"),
        ("pyproject.toml", "dependency_changes"),
        ("src/mergecraft/cli/app.py", "source_without_tests"),
    ],
)
def test_classifier_detects_each_named_category(
    classifier_api: Any, path: str, category: str
) -> None:
    """#48 requires every named category to be observable in the result."""
    result = classifier_api.classify_blast_radius(_change(path, files_changed=1))
    assert category in result.categories


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
def test_rule_set_is_overridable_per_repo(classifier_api: Any) -> None:
    """D9: a repository override changes classification without changing code."""
    from mergecraft.config.settings import RepoSettings

    change = _change("src/mergecraft/utils/time.py", files_changed=1)
    default = classifier_api.classify_blast_radius(change)
    override: dict[str, dict[str, str]] = {"source_without_tests": {"lane": "high"}}
    settings = RepoSettings(blast_radius_override=override)  # type: ignore[call-arg]
    overridden = classifier_api.classify_blast_radius(
        change,
        rule_set=settings.blast_radius_override,  # type: ignore[attr-defined]
    )
    assert default.lane != overridden.lane
    assert overridden.lane == "high"


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
def test_decision_output_names_lane_reason_and_next_action(classifier_api: Any) -> None:
    """#42 requires a user-facing lane, reason, and next action."""
    result = classifier_api.classify_blast_radius(_change("docs/guide.md"))
    assert isinstance(result.lane, str)
    assert result.reason
    assert result.next_action
    assert result.auto_merge_lane == "eligible"


@pytest.mark.xfail(reason="green after W5/W6", strict=False)
def test_classifier_is_pure(classifier_api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Convention 5: classification cannot read files, network, or environment."""
    import builtins
    import os
    import socket

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("classifier performed an external side effect")

    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(os, "environ", {})
    result = classifier_api.classify_blast_radius(_change("docs/guide.md"))
    assert result.lane == "low"
