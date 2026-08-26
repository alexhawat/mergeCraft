"""Lane A AP1.4 — post-run integrity canaries for review sessions (MCB-06)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(
    reason="green after AP5: checkout/config integrity helper",
    strict=False,
)

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
