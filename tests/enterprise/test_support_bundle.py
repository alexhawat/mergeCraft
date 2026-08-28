"""W7.1 — support bundles with secret redaction (#381).

Intended public API (W7.2): ``mergecraft.enterprise.support_bundle``.
Distinct from ``mergecraft.reliability.diagnostic_bundle``.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

_SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


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


def test_support_bundle_missing_destination_parent_is_created(tmp_path: Path) -> None:
    """Edge: nested destination directories are created."""
    from mergecraft.enterprise.support_bundle import write_support_bundle

    destination = tmp_path / "nested" / "out" / "support.tgz"
    written = write_support_bundle(destination, extra_text="ok")
    assert Path(written).is_file()


def test_support_bundle_rejects_non_archive_suffix(tmp_path: Path) -> None:
    """Error: a destination that is not an archive path raises ValueError."""
    from mergecraft.enterprise.support_bundle import write_support_bundle

    with pytest.raises(ValueError, match=r"bundle|archive|tgz"):
        write_support_bundle(tmp_path / "notes.txt", extra_text="ok")


def test_support_bundle_resolves_audit_path_from_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``write_support_bundle(..., root=workspace)`` uses ``resolve_audit_log_path``."""
    from mergecraft.enterprise.audit import (
        MERGECRAFT_AUDIT_ROOT_ENV,
        append_audit_event,
        resolve_audit_log_path,
    )
    from mergecraft.enterprise.support_bundle import write_support_bundle

    workspace = tmp_path / "repo"
    workspace.mkdir()
    audit_root = tmp_path / "audit-root"
    audit_root.mkdir()
    monkeypatch.setenv(MERGECRAFT_AUDIT_ROOT_ENV, str(audit_root))

    append_audit_event(
        {
            "event_type": "terminal_verdict",
            "outcome": "approved",
            "artifact_id": "support-bundle-audit-canary",
            "context": {},
        },
        root=workspace,
    )
    audit_path = resolve_audit_log_path(root=workspace)
    assert audit_path.is_file()

    destination = tmp_path / "bundle.tgz"
    write_support_bundle(destination, extra_text="ok", root=workspace)

    with tarfile.open(destination, "r:gz") as archive:
        extracted = archive.extractfile("diagnostics.txt")
        assert extracted is not None
        content = extracted.read().decode("utf-8")

    assert f"audit_log: {audit_path}" in content
    assert "audit_chain: ok" in content
