"""BR1.4 / BR5 — bounded CI log archive reads (MCB-14, D11/D16)."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from mergecraft.ci.providers.github_actions import GitHubActionsProvider

_TRUNCATION_MARKER = "truncat"


def _build_log_zip(*, member_payload: bytes, declared_size: int | None = None) -> bytes:
    """Build a real zip with attacker-controlled central-directory metadata."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("job/1/step.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        if declared_size is not None:
            info.file_size = declared_size
        archive.writestr(info, member_payload)
    return buffer.getvalue()


def test_high_ratio_archive_is_refused() -> None:
    """D16: a real high-ratio zip must not expand unbounded in memory."""
    raw = _build_log_zip(member_payload=b"A" * 2_000_000, declared_size=64)
    decoded = GitHubActionsProvider._decode_log_archive(raw)
    assert len(decoded.encode("utf-8")) < 2_000_000


def test_member_and_total_caps_are_enforced() -> None:
    """D11: per-member and aggregate caps apply to archive expansion."""
    from mergecraft.ci import providers as providers_pkg

    max_member = getattr(providers_pkg.github_actions, "_MAX_MEMBER_BYTES", None)
    max_total = getattr(providers_pkg.github_actions, "_MAX_TOTAL_BYTES", None)
    if max_member is None or max_total is None:
        pytest.fail("archive bound constants are not defined yet (BR5)")

    parts = [b"B" * (max_member + 1024) for _ in range(3)]
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, payload in enumerate(parts):
            archive.writestr(f"log-{index}.txt", payload)
    raw = buffer.getvalue()
    decoded = GitHubActionsProvider._decode_log_archive(raw)
    assert len(decoded.encode("utf-8")) <= max_total + 256


def test_truncation_is_visible_in_the_output() -> None:
    """D11: truncated archives expose an operator-visible marker."""
    raw = _build_log_zip(member_payload=b"C" * 500_000)
    decoded = GitHubActionsProvider._decode_log_archive(raw)
    assert _TRUNCATION_MARKER in decoded.casefold()
