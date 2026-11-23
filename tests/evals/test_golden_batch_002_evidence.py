"""Keep the staged upstream packets intact as human decisions evolve."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from mergecraft.evals.human_batch import HumanBatchManifest, load_human_batch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "evals/adjudication/golden-batch-002.json"


def _manifest() -> HumanBatchManifest:
    return HumanBatchManifest.model_validate_json(_MANIFEST_PATH.read_bytes())


def test_committed_batch_validates_without_rewriting_human_decisions() -> None:
    """Validate the current decisions, including future confirm/correct/abstain rows."""
    original = _MANIFEST_PATH.read_bytes()
    manifest = load_human_batch(_MANIFEST_PATH, repo_root=_REPO_ROOT)
    assert manifest.batch_id == "golden-batch-002"
    assert _MANIFEST_PATH.read_bytes() == original


@pytest.mark.parametrize("case_id", [row.case_id for row in _manifest().cases])
def test_packet_inventory_matches_every_artifact(case_id: str) -> None:
    row = next(row for row in _manifest().cases if row.case_id == case_id)
    assert row.fixture_path is not None, f"{case_id}: missing local evidence packet"
    evidence_path = _REPO_ROOT / row.fixture_path
    assert sha256(evidence_path.read_bytes()).hexdigest() == row.fixture_sha256
    evidence = json.loads(evidence_path.read_bytes())
    assert evidence["case_id"] == case_id

    # The three independently prepared research groups used these inventory keys.
    inventory = evidence.get(
        "fixture_files_sha256", evidence.get("artifact_hashes", evidence.get("artifactsha256"))
    )
    assert isinstance(inventory, dict), f"{case_id}: invalid artifact inventory"
    assert inventory, f"{case_id}: missing artifact inventory"
    fixture_dir = evidence_path.parent
    artifacts: set[Path] = set()
    for relative, expected in inventory.items():
        path = Path(relative)
        artifact = (
            _REPO_ROOT / path
            if path.parts[:3] == ("evals", "fixtures", "golden")
            else fixture_dir / path
        )
        assert not artifact.is_symlink(), artifact
        assert artifact.resolve().is_relative_to(fixture_dir.resolve()), artifact
        assert sha256(artifact.read_bytes()).hexdigest() == expected, artifact
        artifacts.add(artifact)

    assert artifacts == set(fixture_dir.iterdir()) - {evidence_path}, case_id
