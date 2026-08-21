"""W7.1 — support bundles with secret redaction (#381).

Intended public API (W7.2): ``mergecraft.enterprise.support_bundle``.
Distinct from ``mergecraft.reliability.diagnostic_bundle``.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

_W72 = pytest.mark.xfail(
    reason="green after W7.2: support bundle with redaction (#381)",
    strict=False,
)

_SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


@_W72
def test_support_bundle_redacts_secrets(tmp_path: Path) -> None:
    """Happy: a written support bundle never contains the raw secret material."""
    from mergecraft.enterprise.support_bundle import write_support_bundle

    destination = tmp_path / "support.tgz"
    write_support_bundle(destination, extra_text=f"token={_SECRET}")
    assert destination.is_file()
    with tarfile.open(destination, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        assert members, "support bundle must contain at least one file"
        blobs: list[str] = []
        for member in members:
            extracted = archive.extractfile(member)
            assert extracted is not None
            blobs.append(extracted.read().decode("utf-8", errors="replace"))
    haystack = "\n".join(blobs)
    assert _SECRET not in haystack
    assert "[REDACTED]" in haystack or "redact" in haystack.casefold()


@_W72
def test_support_bundle_missing_destination_parent_is_created(tmp_path: Path) -> None:
    """Edge: nested destination directories are created."""
    from mergecraft.enterprise.support_bundle import write_support_bundle

    destination = tmp_path / "nested" / "out" / "support.tgz"
    written = write_support_bundle(destination, extra_text="ok")
    assert Path(written).is_file()


@_W72
def test_support_bundle_rejects_non_archive_suffix(tmp_path: Path) -> None:
    """Error: a destination that is not an archive path raises ValueError."""
    from mergecraft.enterprise.support_bundle import write_support_bundle

    with pytest.raises(ValueError, match=r"bundle|archive|tgz"):
        write_support_bundle(tmp_path / "notes.txt", extra_text="ok")
