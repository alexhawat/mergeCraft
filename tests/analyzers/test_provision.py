"""Pinned binary provisioning and lockfile reproducibility (D10, D24)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import import_module, skip_if_github_release_outage


def test_checksum_mismatch_fails_before_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )

    def _write_junk(_url: str, dest: Path) -> None:
        dest.write_bytes(b"not-the-pinned-artifact")

    monkeypatch.setattr(provision, "_download_pinned_url", _write_junk)
    with pytest.raises(provision.ProvisionError, match=r"sha256|checksum|mismatch"):
        provision.provision_managed_binary(
            manifest=m,
            platform="linux-amd64",
            cache_dir=tmp_path,
            expected_sha256="deadbeef" * 8,
        )


def test_unpinned_download_path_does_not_exist(tmp_path: Path) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    with pytest.raises((provision.ProvisionError, AttributeError), match=r"pin|sha256|provenance"):
        provision.fetch_unpinned(url="https://example.com/tool", cache_dir=tmp_path)


def test_lockfile_records_resolved_tool_and_checksum(tmp_path: Path) -> None:
    lockfile = import_module("mergecraft.analyzers.lockfile")
    entry = lockfile.LockEntry(
        tool_id="actionlint",
        version="1.7.12",
        mode="managed",
        source="cache",
        sha256="abc123",
    )
    path = tmp_path / ".mergecraft" / "analyzers.lock"
    lockfile.write_lock(path, [entry])
    loaded = lockfile.read_lock(path)
    assert loaded[0].tool_id == "actionlint"
    assert loaded[0].sha256 == "abc123"


def test_two_runs_at_same_lock_resolve_identically(tmp_path: Path) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    try:
        first = provision.resolve_with_lock(
            manifest=m,
            lock_path=lock_path,
            cache_dir=tmp_path / "cache",
            platform="linux-amd64",
        )
    except provision.ProvisionError as exc:
        skip_if_github_release_outage(str(exc))
        raise
    second = provision.resolve_with_lock(
        manifest=m, lock_path=lock_path, cache_dir=tmp_path / "cache", platform="linux-amd64"
    )
    assert first.resolved_path == second.resolved_path
    assert first.sha256 == second.sha256


def test_github_release_outage_is_an_environment_skip() -> None:
    with pytest.raises(pytest.skip.Exception, match="504 Gateway Time-out"):
        skip_if_github_release_outage(
            "Server error '504 Gateway Time-out' for url 'https://github.com/'"
        )
