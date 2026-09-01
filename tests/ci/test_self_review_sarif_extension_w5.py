"""W1.5 — optional CI SARIF extension contracts (lane D, green after W5).

W5 ships actionlint / zizmor / semgrep SARIF uploads and config names.
trufflehog is a named D12 skip — JSONL-only, no SARIF emitter on this surface.
"""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest
import yaml

from tests.ci.test_ci_sarif_evidence_464 import _upload_artifact_names
from tests.ci.workflow_support import REPO_ROOT, load_workflow, read_text

_SHIPPED_EXTENDED_ARTIFACTS = (
    "actionlint-sarif",
    "zizmor-sarif",
    "semgrep-sarif",
)
_TRUFFLEHOG_ARTIFACT = "trufflehog-sarif"
_FIRST_WAVE = ("ruff-sarif", "mypy-sarif", "bandit-sarif")


@pytest.mark.parametrize("artifact_name", _SHIPPED_EXTENDED_ARTIFACTS)
def test_ci_yml_uploads_extended_sarif_artifact(artifact_name: str) -> None:
    """W5 — actionlint / zizmor / semgrep upload SARIF artifacts from ``ci.yml``."""
    doc = load_workflow("ci.yml")
    uploaded = _upload_artifact_names(doc)
    assert artifact_name in uploaded


def test_ci_yml_does_not_upload_trufflehog_sarif() -> None:
    """D12 — trufflehog has no SARIF emitter; ``ci.yml`` must not upload it."""
    doc = load_workflow("ci.yml")
    uploaded = _upload_artifact_names(doc)
    assert _TRUFFLEHOG_ARTIFACT not in uploaded


def test_committed_config_lists_shipped_extended_sarif_artifacts() -> None:
    """W5 — ``ciEvidence.sarifArtifacts`` lists shipped W5 names beside the first wave."""
    config_path = REPO_ROOT / ".mergecraft" / "config.yaml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    ci_evidence = loaded.get("ciEvidence") or {}
    assert isinstance(ci_evidence, dict)
    artifacts = ci_evidence.get("sarifArtifacts") or []
    assert isinstance(artifacts, list)
    for name in _FIRST_WAVE:
        assert name in artifacts
    for name in _SHIPPED_EXTENDED_ARTIFACTS:
        assert name in artifacts


def test_committed_config_omits_trufflehog_sarif_artifact() -> None:
    """D12 — trufflehog is omitted from ``sarifArtifacts`` (JSONL-only parser)."""
    settings = yaml.safe_load(
        (REPO_ROOT / ".mergecraft" / "config.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(settings, dict)
    ci_evidence = settings.get("ciEvidence") or {}
    assert isinstance(ci_evidence, dict)
    artifacts = ci_evidence.get("sarifArtifacts") or []
    assert _TRUFFLEHOG_ARTIFACT not in artifacts


def test_ci_yml_static_job_sets_workflow_sarif_dir() -> None:
    """W5 — actionlint/zizmor emit step exports ``MERGECRAFT_WORKFLOW_SARIF_DIR``."""
    text = read_text(".github/workflows/ci.yml")
    block_idx = text.index("Emit actionlint and zizmor SARIF")
    block = text[block_idx : block_idx + 400]
    assert "MERGECRAFT_WORKFLOW_SARIF_DIR" in block
    assert ".sarif" in block


def test_ci_yml_security_job_invokes_ci_extended_sarif_script() -> None:
    """W5 — semgrep SARIF is emitted via ``scripts/ci_extended_sarif.py``."""
    text = read_text(".github/workflows/ci.yml")
    block_idx = text.index("Emit semgrep SARIF")
    block = text[block_idx : block_idx + 300]
    assert "scripts/ci_extended_sarif.py" in block


def test_ci_extended_sarif_exports_emit_semgrep_sarif() -> None:
    """W5 deliverable — ``emit_semgrep_sarif`` is importable from the CI helper script."""
    module = importlib.import_module("scripts.ci_extended_sarif")
    emit = getattr(module, "emit_semgrep_sarif", None)
    assert callable(emit)


def test_ci_extended_sarif_cli_requires_output_path() -> None:
    """``ci_extended_sarif.py`` fails fast when invoked without an output path."""
    completed = subprocess.run(
        [sys.executable, "scripts/ci_extended_sarif.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "usage:" in completed.stderr


def test_mergecraft_yml_is_not_the_sarif_upload_surface_guard() -> None:
    """D8 guard — lane D must not move SARIF upload onto ``mergecraft.yml``."""
    text = read_text(".github/workflows/mergecraft.yml")
    for name in _FIRST_WAVE + _SHIPPED_EXTENDED_ARTIFACTS + (_TRUFFLEHOG_ARTIFACT,):
        assert name not in text
