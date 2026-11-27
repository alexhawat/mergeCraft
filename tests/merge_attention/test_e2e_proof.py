"""End-to-end proof detection tests (#1611)."""

from __future__ import annotations

from mergecraft.merge_attention.e2e_proof import (
    detect_user_facing_changes,
    scan_e2e_proof,
    verification_gaps_for_user_facing,
)


def test_detects_ui_path() -> None:
    change = detect_user_facing_changes(["src/components/Widget.tsx"])
    assert change.any_ui


def test_visual_proof_in_pr_body_closes_ui_gap() -> None:
    change = detect_user_facing_changes(["src/components/Widget.tsx"])
    proof = scan_e2e_proof(
        pr_body="![after](https://user-images.githubusercontent.com/1/a.png)",
    )
    assert proof.has_visual_proof
    assert not verification_gaps_for_user_facing(change, proof)


def test_missing_proof_reports_gap() -> None:
    change = detect_user_facing_changes(["src/components/Widget.tsx"])
    proof = scan_e2e_proof(pr_body="No screenshots here.")
    gaps = verification_gaps_for_user_facing(change, proof)
    assert len(gaps) == 1
    assert "screenshot" in gaps[0].lower()


def test_perf_path_requires_bench_proof() -> None:
    change = detect_user_facing_changes(["src/perf/hot_loop.py"])
    proof = scan_e2e_proof(pr_body="Looks faster.")
    gaps = verification_gaps_for_user_facing(change, proof)
    assert gaps
    assert "profil" in gaps[0].lower()


def test_dotgithub_path_not_corrupted_by_path_normalization() -> None:
    """Regression: lstrip('./') mangles paths like `.github/workflows/x.yml`."""
    change = detect_user_facing_changes([".github/workflows/ci.yml"])
    assert not change.any_ui
    assert change.ui_paths == ()


def test_prefixed_relative_path_matches_ui_glob() -> None:
    change = detect_user_facing_changes(["./src/components/Widget.tsx"])
    assert change.any_ui
    assert "src/components/Widget.tsx" in change.ui_paths


def test_custom_perf_glob_merges_with_defaults() -> None:
    change = detect_user_facing_changes(
        ["src/perf/hot_loop.py", "custom/metrics.py"],
        perf_globs=("custom/**",),
    )
    assert change.any_perf
    assert "src/perf/hot_loop.py" in change.perf_paths
    assert "custom/metrics.py" in change.perf_paths
    assert detect_user_facing_changes(["src/perf/hot_loop.py"], perf_globs=()).any_perf
