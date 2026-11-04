"""``policy.evidence``: where a repository declares the proof for a policy evidence key.

``RepoSettings.policy`` is a ``PolicySettings`` whose ``evidence`` maps an evidence
key to an ``EvidenceProducerSettings``. Each declaration names exactly one proof:

* ``checkRun: {name, trustedApps}`` — a check run of that name posted by one of the
  named GitHub Apps. ``github-actions`` is refused: the job names in a
  ``pull_request`` workflow come from the head ref, which the author controls.
* ``artifact: {name}`` — a workflow artifact holding a policy-evidence document.

The suite is written before the settings exist, so it is red until they land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from tests.support.policy_evidence_fixtures import write_config

if TYPE_CHECKING:
    from pathlib import Path


def _settings(evidence: dict[str, Any]) -> Any:
    from mergecraft.config.settings import RepoSettings

    return RepoSettings.model_validate({"policy": {"evidence": evidence}})


def test_policy_evidence_defaults_to_no_declarations() -> None:
    """A repository that declares nothing gets an empty, typed ``policy.evidence``."""
    from mergecraft.config.settings import PolicySettings, default_settings

    settings = default_settings()

    assert isinstance(settings.policy, PolicySettings)
    assert settings.policy.evidence == {}


@pytest.mark.parametrize(
    "declaration",
    [
        {"checkRun": {"name": "Deploy / health", "trustedApps": ["acme-ci"]}},
        {"check_run": {"name": "Deploy / health", "trusted_apps": ["acme-ci"]}},
    ],
    ids=["config-spelling", "field-names"],
)
def test_a_check_run_declaration_parses(declaration: dict[str, Any]) -> None:
    """``checkRun`` carries the run name and the Apps trusted to post it."""
    from mergecraft.config.settings import EvidenceProducerSettings

    settings = _settings({"health_check": declaration})

    producer = settings.policy.evidence["health_check"]
    assert isinstance(producer, EvidenceProducerSettings)
    assert producer.check_run is not None
    assert producer.check_run.name == "Deploy / health"
    assert producer.check_run.trusted_apps == ["acme-ci"]
    assert producer.artifact is None


def test_an_artifact_declaration_parses() -> None:
    """``artifact`` carries the name of the workflow artifact holding the document."""
    settings = _settings({"rollback_plan": {"artifact": {"name": "rollback-proof"}}})

    producer = settings.policy.evidence["rollback_plan"]
    assert producer.artifact is not None
    assert producer.artifact.name == "rollback-proof"
    assert producer.check_run is None


def _errors(excinfo: pytest.ExceptionInfo[ValidationError]) -> list[dict[str, Any]]:
    return [dict(error) for error in excinfo.value.errors()]


def _loc(error: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(part) for part in error["loc"])


_UNDER_DECLARATION = ("policy", "evidence", "health_check")


@pytest.mark.parametrize(
    "declaration",
    [
        {
            "checkRun": {"name": "Deploy / health", "trustedApps": ["acme-ci"]},
            "artifact": {"name": "rollback-proof"},
        },
        {},
    ],
    ids=["both", "neither"],
)
def test_a_declaration_names_exactly_one_proof(declaration: dict[str, Any]) -> None:
    """Both or neither of ``checkRun`` / ``artifact`` is a configuration error."""
    with pytest.raises(ValidationError) as excinfo:
        _settings({"health_check": declaration})

    errors = _errors(excinfo)
    naming_both = [
        error
        for error in errors
        if _loc(error)[:3] == _UNDER_DECLARATION
        and "checkRun" in error["msg"]
        and "artifact" in error["msg"]
    ]
    assert naming_both, f"the error must name both proof kinds for the declaration: {errors}"


@pytest.mark.parametrize("app", ["github-actions", "GitHub-Actions"])
def test_github_actions_is_refused_as_a_trusted_app(app: str) -> None:
    """A head-ref workflow names its own jobs, so its App can never vouch for them."""
    accepted = _settings(
        {"health_check": {"checkRun": {"name": "Deploy / health", "trustedApps": ["acme-ci"]}}}
    )
    assert accepted.policy.evidence["health_check"].check_run.trusted_apps == ["acme-ci"]

    with pytest.raises(ValidationError) as excinfo:
        _settings({"health_check": {"checkRun": {"name": "Deploy / health", "trustedApps": [app]}}})

    errors = _errors(excinfo)
    refusals = [
        error
        for error in errors
        if _loc(error)[:3] == _UNDER_DECLARATION and "github-actions" in error["msg"].casefold()
    ]
    assert refusals, f"the refusal must say github-actions cannot be trusted: {errors}"


def test_a_check_run_declaration_needs_a_name() -> None:
    """A declaration with no run name could only ever match by accident."""
    with pytest.raises(ValidationError) as excinfo:
        _settings({"health_check": {"checkRun": {"trustedApps": ["acme-ci"]}}})

    errors = _errors(excinfo)
    assert any(
        error["type"] == "missing"
        and _loc(error)[:3] == _UNDER_DECLARATION
        and _loc(error)[-1] == "name"
        for error in errors
    ), errors


def test_an_unknown_key_in_a_declaration_is_refused() -> None:
    """A misspelt ``trustedApps`` must fail loudly, not silently trust nobody."""
    with pytest.raises(ValidationError) as excinfo:
        _settings(
            {"health_check": {"checkRun": {"name": "Deploy / health", "trustedApp": ["acme-ci"]}}}
        )

    errors = _errors(excinfo)
    assert any(
        error["type"] == "extra_forbidden"
        and _loc(error)[:3] == _UNDER_DECLARATION
        and _loc(error)[-1] == "trustedApp"
        for error in errors
    ), errors


def test_policy_evidence_loads_from_the_repository_config(tmp_path: Path) -> None:
    """The block round-trips through ``.mergecraft/config.yaml`` like every other key."""
    from mergecraft.config import load_repo_settings

    write_config(
        tmp_path,
        {
            "policy": {
                "evidence": {
                    "health_check": {
                        "checkRun": {"name": "Deploy / health", "trustedApps": ["acme-ci"]}
                    },
                    "contract_schema": {"artifact": {"name": "schema-proof"}},
                }
            }
        },
    )

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    evidence = settings.policy.evidence
    assert set(evidence) == {"health_check", "contract_schema"}
    assert evidence["health_check"].check_run.trusted_apps == ["acme-ci"]
    assert evidence["contract_schema"].artifact.name == "schema-proof"
