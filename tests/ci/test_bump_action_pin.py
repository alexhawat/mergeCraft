"""Real-history coverage for source→manifest→consumer pin preparation."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.ci.test_action_image_digest_check import _git, _history
from tests.ci.workflow_support import REPO_ROOT


def _module(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    return importlib.import_module("bump_action_pin")


def test_manifest_preparation_changes_only_image_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    repo, source, _manifest = _history(tmp_path)
    _git(repo, "checkout", "--detach", source)
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module, "verify_image", lambda repo, digest, sha: seen.append((digest, sha))
    )
    digest = "sha256:" + "b" * 64
    result = module.prepare_manifest(repo, source, digest)
    assert result["state"] == "manifest-change-prepared"
    assert seen == [(digest, source)]
    assert _git(repo, "diff", "--name-only") == "action.yml"
    assert digest in (repo / "action.yml").read_text()
    assert _git(repo, "rev-parse", "HEAD") == source


def test_failed_attestation_cannot_prepare_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    repo, source, _manifest = _history(tmp_path)
    _git(repo, "checkout", "--detach", source)

    def deny(*args: object) -> None:
        raise module.VerificationError("signature rejected")

    monkeypatch.setattr(module, "verify_image", deny)
    with pytest.raises(module.VerificationError):
        module.prepare_manifest(repo, source, "sha256:" + "b" * 64)
    assert not _git(repo, "status", "--porcelain")


def test_pin_requires_manifest_already_in_target_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    repo, source, manifest = _history(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/pre-0.0.1", source)
    with pytest.raises(module.VerificationError):
        module.prepare_pin(repo, manifest)
    assert not _git(repo, "status", "--porcelain")


def test_consumer_pin_uses_c_and_never_built_source_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    repo, source, manifest = _history(tmp_path)
    workflows = repo / ".github/workflows"
    workflows.mkdir(parents=True)
    path = workflows / "mergecraft.yml"
    path.write_text(
        f'env:\n  MERGECRAFT_ACTION_SHA: "{source}"\njobs:\n  review:\n    steps:\n      - uses: alexhawat/mergeCraft@{source}\n'
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: consumer fixture")
    _git(repo, "update-ref", "refs/remotes/origin/pre-0.0.1", manifest)
    from types import SimpleNamespace

    monkeypatch.setattr(
        module,
        "verify_manifest",
        lambda repo, commit: SimpleNamespace(
            source_revision=source, image_digest="sha256:" + "b" * 64
        ),
    )
    result = module.prepare_pin(repo, manifest)
    assert result["state"] == "pin-change-prepared"
    assert source not in path.read_text()
    assert path.read_text().count(manifest) == 2
    _git(repo, "commit", "-am", "test: pin fixture")
    assert module.prepare_pin(repo, manifest)["state"] == "pin-already-present"


def test_existing_unsigned_tag_is_not_rebuilt_or_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    from types import SimpleNamespace

    monkeypatch.setattr(
        module,
        "_ghcr_digest_for_tag",
        lambda tag: SimpleNamespace(
            status=module.TagLookupStatus.FOUND, digest="sha256:" + "d" * 64
        ),
    )

    def deny(*args: object, **kwargs: object) -> None:
        raise module.VerificationError("unsigned tag")

    monkeypatch.setattr(module, "verify_image", deny)
    with pytest.raises(module.VerificationError, match="unsigned"):
        module.resolve_images(tmp_path, "a" * 40)


def test_registry_error_does_not_mean_missing_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    from types import SimpleNamespace

    monkeypatch.setattr(
        module,
        "_ghcr_digest_for_tag",
        lambda tag: SimpleNamespace(status=module.TagLookupStatus.ERROR),
    )
    with pytest.raises(module.VerificationError, match="unavailable"):
        module.resolve_images(tmp_path, "a" * 40)
