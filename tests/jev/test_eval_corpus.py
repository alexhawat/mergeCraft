"""J1.9 — Jev eval corpus and the no-threshold-without-a-row gate (D15)."""

from __future__ import annotations

import json

from tests.jev.support import (
    CORPUS_DIR,
    PACK_IDS,
    import_jev,
    load_corpus,
)


def test_corpus_has_at_least_three_scenarios_per_pack() -> None:
    index = json.loads((CORPUS_DIR / "index.json").read_text(encoding="utf-8"))
    rows = load_corpus()
    assert rows
    by_pack: dict[str, int] = {pack_id: 0 for pack_id in PACK_IDS}
    for row in rows:
        pack_id = str(row["pack_id"])
        assert pack_id in PACK_IDS
        by_pack[pack_id] += 1
    minimum = int(index["min_scenarios_per_pack"])
    for pack_id, count in by_pack.items():
        assert count >= minimum, f"{pack_id} has {count} scenarios, need {minimum}"


def test_every_corpus_row_traces_to_a_shipped_defect() -> None:
    for row in load_corpus():
        defect = row["shipped_defect"]
        assert isinstance(defect, dict)
        assert defect.get("ref")
        assert defect.get("citation")
        assert defect.get("kind")
        assert row["id"].startswith("jev-")
        assert row["pack_id"] in PACK_IDS


def test_every_corpus_row_declares_calibration_targets() -> None:
    for row in load_corpus():
        targets = row.get("calibrates")
        assert isinstance(targets, list)
        assert targets
        for target in targets:
            assert str(target).startswith(f"{row['pack_id']}.")


def test_every_threshold_names_corpus_rows_and_pack_version() -> None:
    policy = import_jev("policy")
    corpus_ids = {str(row["id"]) for row in load_corpus()}
    thresholds = list(policy.iter_thresholds())
    assert thresholds, "J3 must record thresholds next to their pack version"
    for threshold in thresholds:
        assert threshold.pack_id in PACK_IDS
        assert threshold.corpus_ids
        missing = set(threshold.corpus_ids) - corpus_ids
        assert not missing


def test_threshold_without_corpus_row_must_not_merge() -> None:
    policy = import_jev("policy")
    corpus_ids = {str(row["id"]) for row in load_corpus()}
    orphan = [
        threshold
        for threshold in policy.iter_thresholds()
        if not threshold.corpus_ids or set(threshold.corpus_ids).isdisjoint(corpus_ids)
    ]
    assert orphan == []


def test_iter_thresholds_is_the_deliverable_symbol() -> None:
    policy = import_jev("policy")
    first = next(iter(policy.iter_thresholds()))
    assert hasattr(first, "pack_id")
    assert hasattr(first, "corpus_ids")
    assert hasattr(first, "value")
