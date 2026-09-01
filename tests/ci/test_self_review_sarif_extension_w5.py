"""W1.5 — optional CI SARIF extension contracts (lane D, green after W5).

W5 is skipped for this lane unless the operator confirms (S1/D12). These tests
stay xfailed so they never block later stages.
"""

from __future__ import annotations

import pytest
import yaml

from tests.ci.test_ci_sarif_evidence_464 import _upload_artifact_names
from tests.ci.workflow_support import REPO_ROOT, load_workflow, read_text

W5_XFAIL = pytest.mark.xfail(
    reason="green after W5: extend ci.yml SARIF catalog (operator opt-in)",
    strict=True,
)

_EXTENDED_ARTIFACTS = (
    "actionlint-sarif",
    "zizmor-sarif",
    "trufflehog-sarif",
    "semgrep-sarif",
)
_FIRST_WAVE = ("ruff-sarif", "mypy-sarif", "bandit-sarif")


@W5_XFAIL
@pytest.mark.parametrize("artifact_name", _EXTENDED_ARTIFACTS)
def test_ci_yml_uploads_extended_sarif_artifact(artifact_name: str) -> None:
    """D12 — optional tools upload SARIF artifacts from ``ci.yml`` static/security."""
    doc = load_workflow("ci.yml")
    uploaded = _upload_artifact_names(doc)
    assert artifact_name in uploaded


@W5_XFAIL
def test_committed_config_lists_extended_sarif_artifacts() -> None:
    """D12 — ``ciEvidence.sarifArtifacts`` must list W5 names beside the first wave."""
    config_path = REPO_ROOT / ".mergecraft" / "config.yaml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    ci_evidence = loaded.get("ciEvidence") or {}
    assert isinstance(ci_evidence, dict)
    artifacts = ci_evidence.get("sarifArtifacts") or []
    assert isinstance(artifacts, list)
    for name in _FIRST_WAVE:
        assert name in artifacts
    for name in _EXTENDED_ARTIFACTS:
        assert name in artifacts


def test_mergecraft_yml_is_not_the_sarif_upload_surface_guard() -> None:
    """D8 guard — lane D must not move SARIF upload onto ``mergecraft.yml``."""
    text = read_text(".github/workflows/mergecraft.yml")
    for name in _FIRST_WAVE + _EXTENDED_ARTIFACTS:
        assert name not in text
