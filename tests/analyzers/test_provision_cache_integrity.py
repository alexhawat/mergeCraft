"""Managed-binary cache integrity after provisioning (D10).

The sha-keyed cache directory is keyed by the *archive* pin, so it proves nothing
about the extracted binary on later runs. TruffleHog rewrites its own binary in
place via its built-in updater; these tests cover both defences — the recorded
receipt that stops a mutated binary from ever being executed, and the argv flag
that stops the updater from firing in the first place.

No test here touches the network: ``_download_pinned_url`` is always faked.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from tests.analyzers.support import import_module

_PAYLOAD = b"#!/bin/sh\necho pinned-tool 1.0.0\n"
_PAYLOAD_SHA = hashlib.sha256(_PAYLOAD).hexdigest()
_PLATFORM = "linux-amd64"


def _manifest(sha256: str = _PAYLOAD_SHA) -> Any:
    """Build a managed manifest whose pinned artifact is the raw fake binary."""
    manifest = import_module("mergecraft.analyzers.manifest")
    return manifest.AnalyzerManifest.model_validate(
        {
            "id": "faketool",
            "category": "ci",
            "languages": [],
            "detect": {"files": ["**/*"]},
            "command": ["faketool", "{files}"],
            "scope": "diff",
            "parser": "sarif",
            "supports_fix": False,
            "default_enabled": "auto",
            "version": "1.0.0",
            "runtime": "managed",
            "timeout_s": 60,
            "trust": "untrusted",
            "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
            "provenance": {
                _PLATFORM: {"url": "https://example.invalid/faketool", "sha256": sha256}
            },
            "network_allowlist": [],
        }
    )


@pytest.fixture
def fake_download(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the pinned download with a local write; return the call log."""
    provision = import_module("mergecraft.analyzers.provision")
    calls: list[str] = []

    def _fake(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(_PAYLOAD)

    monkeypatch.setattr(provision, "_download_pinned_url", _fake)
    return calls


def _provision(cache_dir: Path) -> Any:
    provision = import_module("mergecraft.analyzers.provision")
    return provision.provision_managed_binary(
        manifest=_manifest(), platform=_PLATFORM, cache_dir=cache_dir
    )


def test_unmodified_cached_binary_is_reused_without_redownloading(
    tmp_path: Path, fake_download: list[str]
) -> None:
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    second = _provision(cache_dir)

    assert first.source == "download"
    assert second.source == "cache"
    assert second.resolved_path == first.resolved_path
    assert second.sha256 == first.sha256 == _PAYLOAD_SHA
    assert fake_download == ["https://example.invalid/faketool"]


def test_receipt_records_the_installed_binary_digest(
    tmp_path: Path, fake_download: list[str]
) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    result = _provision(tmp_path / "cache")
    recorded = provision.read_provision_receipt(result.resolved_path.parent)

    assert recorded == _PAYLOAD_SHA


def test_binary_mutated_after_provisioning_is_never_executed(
    tmp_path: Path, fake_download: list[str]
) -> None:
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    # Stand in for TruffleHog's self-updater: rewrite the binary in place and drop
    # the updater's sibling state file next to it.
    first.resolved_path.write_bytes(b"#!/bin/sh\necho attacker 9.9.9\n")
    (first.resolved_path.parent / "faketool-updates.lock").write_text("stale", encoding="utf-8")

    second = _provision(cache_dir)

    assert second.source == "download", "mutated cache must not be served as a cache hit"
    assert second.sha256 == _PAYLOAD_SHA
    assert second.resolved_path.read_bytes() == _PAYLOAD
    assert not (second.resolved_path.parent / "faketool-updates.lock").exists()
    assert len(fake_download) == 2


def test_mutated_binary_is_refused_when_repinning_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_download: list[str]
) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    first.resolved_path.write_bytes(b"#!/bin/sh\necho attacker 9.9.9\n")

    def _offline(url: str, dest: Path) -> None:
        msg = f"download failed for {url!r}: offline"
        raise provision.ProvisionError(msg)

    monkeypatch.setattr(provision, "_download_pinned_url", _offline)

    with pytest.raises(provision.ProvisionError, match=r"download failed"):
        _provision(cache_dir)

    assert not first.resolved_path.exists(), "the mutated binary must not survive as runnable"


def test_cache_without_a_receipt_is_reprovisioned(tmp_path: Path, fake_download: list[str]) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    # A cache directory written by a mergeCraft that predates receipts.
    (first.resolved_path.parent / provision.RECEIPT_NAME).unlink()

    second = _provision(cache_dir)

    assert second.source == "download"
    assert len(fake_download) == 2


def test_lock_resolution_reprovisions_a_mutated_cache(
    tmp_path: Path, fake_download: list[str]
) -> None:
    provision = import_module("mergecraft.analyzers.provision")
    cache_dir = tmp_path / "cache"
    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    manifest = _manifest()
    first = provision.resolve_with_lock(
        manifest=manifest, lock_path=lock_path, cache_dir=cache_dir, platform=_PLATFORM
    )
    first.resolved_path.write_bytes(b"#!/bin/sh\necho attacker 9.9.9\n")

    second = provision.resolve_with_lock(
        manifest=manifest, lock_path=lock_path, cache_dir=cache_dir, platform=_PLATFORM
    )

    assert second.sha256 == _PAYLOAD_SHA
    assert second.resolved_path.read_bytes() == _PAYLOAD
    assert len(fake_download) == 2


def _finalized_trufflehog_argv(repo_root: Path, argv: tuple[str, ...]) -> tuple[str, ...]:
    execution = import_module("mergecraft.analyzers.execution")
    registry = import_module("mergecraft.analyzers.registry")
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = registry.get_manifest("trufflehog")
    plan = resolve.AnalyzerPlan(manifest_id="trufflehog", mode="managed", argv=argv)
    finalized = execution.finalize_plan(
        plan,
        manifest=manifest,
        repo_root=repo_root,
        changed_files=["config/planted-secret.env"],
        tier="untrusted",
    )
    return finalized.argv


def test_trufflehog_manifest_command_disables_the_self_updater() -> None:
    registry = import_module("mergecraft.analyzers.registry")
    command = registry.get_manifest("trufflehog").command

    assert "--no-update" in command


def test_trufflehog_argv_carries_no_update_exactly_once(tmp_path: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    argv = _finalized_trufflehog_argv(tmp_path, tuple(registry.get_manifest("trufflehog").command))

    assert argv.count("--no-update") == 1


def test_trufflehog_custom_argv_still_disables_the_self_updater(tmp_path: Path) -> None:
    # MCP callers assemble their own argv (see ``execution.run_argv``); the flag
    # must be added there too, not only via the manifest command.
    argv = _finalized_trufflehog_argv(tmp_path, ("trufflehog", "filesystem", "-j", "{files}"))

    assert argv.count("--no-update") == 1
