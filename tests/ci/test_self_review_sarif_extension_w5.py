"""W1.5 — CI SARIF extension contracts (lane D W5 + trufflehog CI evidence).

W5 ships actionlint / zizmor / semgrep SARIF uploads and config names.
Trufflehog catalog output is JSONL; CI converts it to SARIF and uploads
``trufflehog-sarif`` so ingest stays one path.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.ci.test_ci_sarif_evidence_464 import _upload_artifact_names
from tests.ci.workflow_support import REPO_ROOT, load_workflow, read_text

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_SHIPPED_EXTENDED_ARTIFACTS = (
    "actionlint-sarif",
    "zizmor-sarif",
    "semgrep-sarif",
    "trufflehog-sarif",
)
_TRUFFLEHOG_ARTIFACT = "trufflehog-sarif"
_FIRST_WAVE = ("ruff-sarif", "mypy-sarif", "bandit-sarif")


@pytest.mark.parametrize("artifact_name", _SHIPPED_EXTENDED_ARTIFACTS)
def test_ci_yml_uploads_extended_sarif_artifact(artifact_name: str) -> None:
    """W5 — extended SARIF artifacts upload from ``ci.yml``."""
    doc = load_workflow("ci.yml")
    uploaded = _upload_artifact_names(doc)
    assert artifact_name in uploaded


def test_ci_yml_uploads_trufflehog_sarif() -> None:
    """CI evidence — ``ci.yml`` uploads converted trufflehog SARIF."""
    doc = load_workflow("ci.yml")
    uploaded = _upload_artifact_names(doc)
    assert _TRUFFLEHOG_ARTIFACT in uploaded


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


def test_committed_config_lists_trufflehog_sarif_artifact() -> None:
    """CI evidence — ``sarifArtifacts`` includes the converted trufflehog artifact."""
    settings = yaml.safe_load(
        (REPO_ROOT / ".mergecraft" / "config.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(settings, dict)
    ci_evidence = settings.get("ciEvidence") or {}
    assert isinstance(ci_evidence, dict)
    artifacts = ci_evidence.get("sarifArtifacts") or []
    assert _TRUFFLEHOG_ARTIFACT in artifacts


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


def test_ci_yml_security_job_invokes_trufflehog_sarif() -> None:
    """CI evidence — trufflehog SARIF is emitted via ``ci_extended_sarif.py trufflehog``."""
    text = read_text(".github/workflows/ci.yml")
    block_idx = text.index("Emit trufflehog SARIF")
    block = text[block_idx : block_idx + 400]
    assert "scripts/ci_extended_sarif.py" in block
    assert "trufflehog" in block
    assert ".sarif/trufflehog.sarif" in block


def test_ci_extended_sarif_exports_emit_semgrep_sarif() -> None:
    """W5 deliverable — ``emit_semgrep_sarif`` is importable from the CI helper script."""
    module = importlib.import_module("scripts.ci_extended_sarif")
    emit = getattr(module, "emit_semgrep_sarif", None)
    assert callable(emit)


def test_ci_extended_sarif_exports_emit_trufflehog_sarif() -> None:
    """CI evidence — ``emit_trufflehog_sarif`` is importable from the CI helper script."""
    module = importlib.import_module("scripts.ci_extended_sarif")
    emit = getattr(module, "emit_trufflehog_sarif", None)
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
    for name in _FIRST_WAVE + _SHIPPED_EXTENDED_ARTIFACTS:
        assert name not in text


def test_emit_trufflehog_empty_scan_writes_empty_results_sarif(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A clean scan must still write a valid SARIF document, never a 0-byte file."""
    module = importlib.import_module("scripts.ci_extended_sarif")

    def _dummy_argv(**_kwargs: object) -> list[str]:
        return ["trufflehog"]

    monkeypatch.setattr(module, "_trufflehog_scan_argv", _dummy_argv)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["trufflehog"], returncode=0, stdout="", stderr=""
        ),
    )
    out = tmp_path / "trufflehog.sarif"
    module.emit_trufflehog_sarif(out=out, repo_root=tmp_path)
    assert out.is_file()
    assert out.stat().st_size > 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "trufflehog"
    assert doc["runs"][0]["results"] == []


def test_emit_trufflehog_does_not_copy_raw_secret(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    planted = "AKIA_PLANTED_FIXTURE_DO_NOT_ROTATE_IN_TESTS"
    payload = json.dumps(
        {
            "SourceMetadata": {
                "Data": {"Filesystem": {"file": "config/planted-secret.env", "line": 1}}
            },
            "DetectorName": "AWSAccessKey",
            "Verified": False,
            "Raw": planted,
            "RawV2": planted,
        }
    )
    module = importlib.import_module("scripts.ci_extended_sarif")
    monkeypatch.setattr(module, "_trufflehog_scan_argv", lambda **_kwargs: ["trufflehog"])
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["trufflehog"], returncode=0, stdout=payload + "\n", stderr=""
        ),
    )
    out = tmp_path / "trufflehog.sarif"
    module.emit_trufflehog_sarif(out=out, repo_root=tmp_path)
    dumped = out.read_text(encoding="utf-8")
    assert planted not in dumped
    doc = json.loads(dumped)
    assert doc["runs"][0]["results"][0]["ruleId"] == "AWSAccessKey"


def test_emit_trufflehog_truncated_jsonl_does_not_write_sarif(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module = importlib.import_module("scripts.ci_extended_sarif")
    monkeypatch.setattr(module, "_trufflehog_scan_argv", lambda **_kwargs: ["trufflehog"])
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["trufflehog"],
            returncode=0,
            stdout='{"SourceMetadata":{"Data":',
            stderr="",
        ),
    )
    out = tmp_path / "trufflehog.sarif"
    with pytest.raises(module.EmitError):
        module.emit_trufflehog_sarif(out=out, repo_root=tmp_path)
    assert not out.exists()


def test_write_trufflehog_exclude_paths_is_regex_file(tmp_path: Path) -> None:
    """3.96.0 ``filesystem`` takes regexes via ``--exclude-paths``, not globs."""
    module = importlib.import_module("scripts.ci_extended_sarif")
    path = module.write_trufflehog_exclude_paths(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "--exclude-globs" not in text
    assert r"\.git/" in text
    assert "node_modules/" in text


def test_trufflehog_scan_argv_uses_exclude_paths_not_exclude_globs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Pinned 3.96.0 rejects ``--exclude-globs`` on ``filesystem``."""
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.analyzers.resolve import AnalyzerPlan

    module = importlib.import_module("scripts.ci_extended_sarif")

    def _fake_provision(plan: object, **_kwargs: object) -> AnalyzerPlan:
        _ = plan
        return AnalyzerPlan(
            manifest_id="trufflehog",
            mode="managed",
            argv=("trufflehog", "filesystem", "-j", "."),
        )

    monkeypatch.setattr("mergecraft.analyzers.execution.provision_managed_argv", _fake_provision)
    exclude = module.write_trufflehog_exclude_paths(tmp_path)
    argv = module._trufflehog_scan_argv(
        manifest=get_manifest("trufflehog"),
        repo_root=tmp_path,
        exclude_paths=exclude,
    )
    assert "--exclude-globs" not in argv
    assert "--exclude-paths" in argv
    assert str(exclude) in argv
