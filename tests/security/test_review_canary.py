"""Lane A AP1.4 — post-run integrity canaries for review sessions (MCB-06)."""

from __future__ import annotations

from pathlib import Path

import pytest

_OUTSIDE_CANARY = "MERGECRAFT_OUTSIDE_CHECKOUT_CANARY_AP1"
_PROVIDER_CANARY = "MERGECRAFT_PROVIDER_KEY_CANARY_AP1"


def test_outside_checkout_canary_is_unreadable(tmp_path: Path) -> None:
    from mergecraft.security.review_integrity import assert_checkout_read_boundary

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / _OUTSIDE_CANARY
    canary.write_text("secret\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        assert_checkout_read_boundary(checkout, [canary])


def test_provider_key_canary_does_not_reach_a_local_sink(tmp_path: Path) -> None:
    from mergecraft.security.review_integrity import scan_local_sinks_for_secrets

    sink = tmp_path / "sink.log"
    sink.write_text("benign\n", encoding="utf-8")
    assert _PROVIDER_CANARY not in scan_local_sinks_for_secrets(
        tmp_path, secrets=[_PROVIDER_CANARY]
    )


def test_scan_returns_sink_paths_and_never_contents(tmp_path: Path) -> None:
    """Returning the contents is itself the leak: a caller that logs the result
    prints the credential the helper exists to catch. Only paths travel."""
    from mergecraft.security.review_integrity import scan_local_sinks_for_secrets

    sink = tmp_path / "sink.log"
    sink.write_text(f"prefix {_PROVIDER_CANARY} suffix\n", encoding="utf-8")

    result = scan_local_sinks_for_secrets(tmp_path, secrets=[_PROVIDER_CANARY])

    matched = {Path(item) for item in result}
    assert matched == {sink}, result
    assert all(_PROVIDER_CANARY not in str(item) for item in matched), result
    assert _PROVIDER_CANARY not in str(result), result


def test_scan_returns_nothing_for_clean_sinks(tmp_path: Path) -> None:
    from mergecraft.security.review_integrity import scan_local_sinks_for_secrets

    (tmp_path / "sink.log").write_text("nothing to see\n", encoding="utf-8")
    assert list(scan_local_sinks_for_secrets(tmp_path, secrets=[_PROVIDER_CANARY])) == []


def test_config_yaml_is_unwritable_during_review(tmp_path: Path) -> None:
    from mergecraft.security.review_integrity import hash_tree, verify_tree_unchanged

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    config_dir = checkout / ".mergecraft"
    config_dir.mkdir()
    config = config_dir / "config.yaml"
    config.write_text("review: true\n", encoding="utf-8")
    before = hash_tree(checkout)
    config.write_text("review: false\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_tree_unchanged(checkout, before)


def test_hash_tree_does_not_follow_symlink_to_outside_file(tmp_path: Path) -> None:
    from mergecraft.security.review_integrity import hash_tree

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (checkout / "escape").symlink_to(outside)

    before = hash_tree(checkout)
    outside.write_text("tampered\n", encoding="utf-8")
    assert hash_tree(checkout) == before

    (checkout / "escape").unlink()
    (checkout / "escape").symlink_to("../outside-secret.txt")
    assert hash_tree(checkout) != before


def test_hash_tree_detects_directory_symlink_retarget(tmp_path: Path) -> None:
    from mergecraft.security.review_integrity import hash_tree

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    target_a = tmp_path / "target-a"
    target_b = tmp_path / "target-b"
    target_a.mkdir()
    target_b.mkdir()
    (target_a / "marker.txt").write_text("a\n", encoding="utf-8")
    (target_b / "marker.txt").write_text("b\n", encoding="utf-8")
    link = checkout / "linked-dir"
    link.symlink_to(target_a, target_is_directory=True)

    before = hash_tree(checkout)
    link.unlink()
    link.symlink_to(target_b, target_is_directory=True)
    assert hash_tree(checkout) != before


def test_analyzer_runtime_files_written_mid_review_keep_the_tree_unchanged(tmp_path: Path) -> None:
    """A ``run_analyzers`` call made mid-review must not fail the integrity gate.

    Unsandboxed, a gate persists output to ``.mergecraft/analyzer-runs`` and
    provisioning writes ``.mergecraft/analyzers.lock`` under its ``.lock``
    sidecar — all after the baseline. Seen on a live review: the only changed
    paths were these three, and the run failed closed.
    """
    from mergecraft.analyzers.lockfile import LockEntry, write_lock
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import _run_tmpdir
    from mergecraft.security.review_integrity import hash_tree, verify_tree_unchanged

    checkout = tmp_path / "checkout"
    (checkout / ".mergecraft").mkdir(parents=True)
    (checkout / ".mergecraft" / "config.yaml").write_text("review: true\n", encoding="utf-8")
    before = hash_tree(checkout)

    runs = _run_tmpdir(AnalyzerPlan(manifest_id="actionlint", mode="managed", cwd=checkout))
    (runs / "actionlint.out").write_text("ok\n", encoding="utf-8")
    write_lock(
        checkout / ".mergecraft" / "analyzers.lock",
        [LockEntry("actionlint", "1.7.12", "managed", "cache", "abc123")],
    )
    assert runs == checkout / ".mergecraft" / "analyzer-runs"
    assert (checkout / ".mergecraft" / "analyzers.lock.lock").exists()
    verify_tree_unchanged(checkout, before)


@pytest.mark.parametrize(
    "rel",
    [
        ".mergecraft/config.yaml",
        ".mergecraft/learnings.md",
        ".mergecraft/analyzers.lock.bak",
        ".mergecraft/analyzer-runs.txt",
        "src/.mergecraft/analyzers.lock",
    ],
)
def test_paths_next_to_the_analyzer_runtime_files_stay_covered(tmp_path: Path, rel: str) -> None:
    from mergecraft.security.review_integrity import hash_tree, verify_tree_unchanged

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    before = hash_tree(checkout)
    path = checkout / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("written mid-review\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_tree_unchanged(checkout, before)
