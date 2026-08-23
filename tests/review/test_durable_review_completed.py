"""CD #453 RED — durable completed review store (D4).

Pins persistence of ``ReviewSnapshot`` + run manifest + findings + evidence so
``findings`` / ``explain`` / ``replay`` can resolve by review id without
re-running the review agent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.review.support_durable_review import (
    artifact_paths,
    build_completed_review,
    completed_review_dir,
    read_json,
    require_attr,
    require_callable,
    sample_fingerprint,
    sample_manifest,
    sample_review_id,
    sample_snapshot,
    seed_completed_review,
)

pytestmark = pytest.mark.xfail(reason="green after CD", strict=False)


def test_persist_completed_review_writes_stable_review_id(tmp_path: Path) -> None:
    """Happy — persisted review id is stable and reloadable."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id)
    load = require_callable("load_completed_review")
    loaded = load(review_id, repo_root=tmp_path)
    assert loaded is not None
    assert loaded.review_id == review_id


def test_persist_stores_snapshot_manifest_and_findings(tmp_path: Path) -> None:
    """D4 — durable review composes snapshot + manifest + findings on disk."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id)
    paths = artifact_paths(tmp_path, review_id)
    for path in paths.values():
        assert path.is_file(), f"missing artifact {path.name}"
    snapshot_payload = read_json(paths["snapshot.json"])
    manifest_payload = read_json(paths["manifest.json"])
    findings_payload = read_json(paths["findings.json"])
    assert snapshot_payload["entry"] == "cli"
    assert manifest_payload["agent_id"] == "mergecraft"
    assert isinstance(findings_payload.get("findings"), list)
    assert findings_payload["findings"][0]["fingerprint"] == sample_fingerprint()


def test_load_returns_none_for_unknown_review_id(tmp_path: Path) -> None:
    """Error — unknown review ids are a miss, not a crash."""
    load = require_callable("load_completed_review")
    assert load("review-does-not-exist", repo_root=tmp_path) is None


def test_load_returns_none_for_corrupt_completed_record(tmp_path: Path) -> None:
    """Error — corrupt JSON under ``.mergecraft/reviews`` is a miss."""
    review_id = sample_review_id()
    root = completed_review_dir(tmp_path, review_id)
    root.mkdir(parents=True)
    (root / "findings.json").write_text("{not-json", encoding="utf-8")
    load = require_callable("load_completed_review")
    assert load(review_id, repo_root=tmp_path) is None


def test_list_completed_review_ids_returns_persisted_ids(tmp_path: Path) -> None:
    """Happy — operators can enumerate stored completed reviews."""
    first = "review-cd-alpha"
    second = "review-cd-beta"
    seed_completed_review(tmp_path, review_id=first)
    seed_completed_review(tmp_path, review_id=second)
    list_ids = require_callable("list_completed_review_ids")
    assert sorted(list_ids(repo_root=tmp_path)) == sorted([first, second])


def test_completed_review_dir_lives_under_mergecraft_reviews(tmp_path: Path) -> None:
    """Unit — storage root is ``<repo>/.mergecraft/reviews/<review_id>``."""
    review_id = sample_review_id()
    path = seed_completed_review(tmp_path, review_id=review_id)
    expected = completed_review_dir(tmp_path, review_id)
    assert path == expected
    assert expected.is_relative_to(tmp_path / ".mergecraft" / "reviews")


def test_completed_review_model_round_trips_required_fields(tmp_path: Path) -> None:
    """Unit — ``CompletedReview`` keeps snapshot, manifest, and findings together."""
    completed_cls = require_attr("CompletedReview")
    review = build_completed_review()
    assert isinstance(review, completed_cls)
    assert review.snapshot.entry == sample_snapshot().entry
    assert review.manifest["agent_id"] == sample_manifest()["agent_id"]
    assert review.findings[0]["fingerprint"] == sample_fingerprint()
    schema_version = require_attr("COMPLETED_REVIEW_SCHEMA_VERSION")
    persist = require_callable("persist_completed_review")
    persist(review, repo_root=tmp_path)
    marker = completed_review_dir(tmp_path, review.review_id) / "completed.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["schema_version"] == schema_version
    assert payload["review_id"] == review.review_id
