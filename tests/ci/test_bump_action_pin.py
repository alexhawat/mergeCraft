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
    assert result["manifest_commit"] is None
    assert module.prepare_manifest(repo, source, digest) == result


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
    assert module.prepare_pin(repo, manifest) == result
    _git(repo, "commit", "-am", "test: pin fixture")
    assert module.prepare_pin(repo, manifest)["state"] == "pin-already-present"


def test_existing_unsigned_tag_is_not_rebuilt_or_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    from types import SimpleNamespace

    monkeypatch.setattr(
        module,
        "_ghcr_digest_for_tag_once",
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
        "_ghcr_digest_for_tag_once",
        lambda tag: SimpleNamespace(status=module.TagLookupStatus.ERROR),
    )
    with pytest.raises(module.VerificationError, match="unavailable"):
        module.resolve_images(tmp_path, "a" * 40)


@pytest.mark.parametrize("dirty", ["staged", "untracked", "runtime", "wrong-image", "mode"])
def test_prepared_manifest_rejects_unrelated_or_staged_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dirty: str
) -> None:
    module = _module(monkeypatch)
    repo, source, _manifest = _history(tmp_path)
    _git(repo, "checkout", "--detach", source)
    monkeypatch.setattr(module, "verify_image", lambda *args: None)
    digest = "sha256:" + "b" * 64
    module.prepare_manifest(repo, source, digest)
    if dirty == "staged":
        _git(repo, "add", "action.yml")
    elif dirty == "untracked":
        (repo / "untracked").write_text("unexpected")
    elif dirty == "runtime":
        (repo / "runtime.py").write_text("VALUE = 2\n")
    elif dirty == "wrong-image":
        path = repo / "action.yml"
        path.write_text(path.read_text().replace("b" * 64, "c" * 64))
    else:
        (repo / "action.yml").chmod(0o755)
    with pytest.raises(module.VerificationError):
        module.prepare_manifest(repo, source, digest)


def test_already_present_manifest_reports_existing_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    repo, source, _manifest = _history(tmp_path)
    _git(repo, "checkout", "--detach", source)
    monkeypatch.setattr(module, "verify_image", lambda *args: None)
    result = module.prepare_manifest(repo, source, "sha256:" + "a" * 64)
    assert result["state"] == "manifest-already-present"
    assert result["manifest_commit"] == source
    assert not _git(repo, "status", "--porcelain")


def test_env_only_consumer_is_supported_and_prepared_rerun_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    module = _module(monkeypatch)
    repo, source, manifest = _history(tmp_path)
    path = repo / ".github/workflows/mergecraft.yml"
    path.parent.mkdir(parents=True)
    path.write_text(f'env:\n  MERGECRAFT_ACTION_SHA: "{source}"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: env-only consumer")
    _git(repo, "update-ref", "refs/remotes/origin/pre-0.0.1", manifest)
    monkeypatch.setattr(
        module,
        "verify_manifest",
        lambda *args: SimpleNamespace(source_revision=source, image_digest="sha256:" + "b" * 64),
    )
    first = module.prepare_pin(repo, manifest)
    assert first["state"] == "pin-change-prepared"
    assert manifest in path.read_text()
    assert module.prepare_pin(repo, manifest) == first
    _git(repo, "add", ".")
    with pytest.raises(module.VerificationError, match="staged"):
        module.prepare_pin(repo, manifest)


def test_shared_repository_drift_fails_before_registry_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(monkeypatch)
    monkeypatch.setenv("IMAGE_ANALYZERS", "ghcr.io/alexhawat/other-package")

    def unexpected(*args: object) -> None:
        pytest.fail("registry access must not occur for unsupported repository configuration")

    monkeypatch.setattr(module, "_ghcr_digest_for_tag_once", unexpected)
    with pytest.raises(module.VerificationError, match="shared repository"):
        module.resolve_images(tmp_path, "a" * 40)


def test_failed_staging_attempt_can_restart_without_unsigned_canonical_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    module = _module(monkeypatch)
    source = "a" * 40
    tags: dict[str, str] = {}
    verified: set[str] = set()
    attempts: list[tuple[str, str]] = []

    def lookup(tag: str) -> Any:
        return SimpleNamespace(
            status=module.TagLookupStatus.FOUND if tag in tags else module.TagLookupStatus.MISSING,
            digest=tags.get(tag),
        )

    def verify(repo: Path, digest: str, sha: str, **kwargs: object) -> str:
        assert sha == source
        if digest not in verified:
            raise module.VerificationError("signature absent")
        return source

    def run(repo: Path, argv: list[str]) -> str:
        assert argv[:5] == ["docker", "buildx", "imagetools", "create", "--prefer-index=false"]
        tag = argv[argv.index("--tag") + 1].split(":")[-1]
        digest = argv[-1].split("@")[-1]
        attempts.append((tag, digest))
        tags[tag] = digest
        return ""

    monkeypatch.setattr(module, "_ghcr_digest_for_tag_once", lookup)
    monkeypatch.setattr(module, "_ghcr_digest_for_tag", lookup)
    monkeypatch.setattr(module, "verify_image", verify)
    monkeypatch.setattr(module, "_run", run)
    assert module.resolve_images(tmp_path, source) == {"slim_digest": "", "analyzers_digest": ""}
    tags["staging-42-1-slim"] = "sha256:" + "b" * 64
    # Failed scan/sign left staging only. Re-run-all starts without trusting it.
    assert module.resolve_images(tmp_path, source) == {"slim_digest": "", "analyzers_digest": ""}
    digests = {"slim": "sha256:" + "c" * 64, "analyzers": "sha256:" + "d" * 64}
    with pytest.raises(module.VerificationError, match="signature"):
        module.publish_canonical(tmp_path, source, digests)
    assert not attempts
    verified.update(digests.values())
    # A conflict in the SECOND kind must not publish the first one.
    tags[f"analyzers-{source}"] = "sha256:" + "f" * 64
    with pytest.raises(module.VerificationError, match="different digest"):
        module.publish_canonical(tmp_path, source, digests)
    assert not attempts
    del tags[f"analyzers-{source}"]
    # Simulate interruption after only slim was published; retry finishes analyzers.
    tags[source] = digests["slim"]
    module.publish_canonical(tmp_path, source, digests)
    assert attempts == [(f"analyzers-{source}", digests["analyzers"])]
    tags.clear()
    attempts.clear()
    module.publish_canonical(tmp_path, source, digests)
    assert tags[source] == digests["slim"]
    assert tags[f"analyzers-{source}"] == digests["analyzers"]
    assert len(attempts) == 2
    module.publish_canonical(tmp_path, source, digests)
    assert len(attempts) == 2
    different = {**digests, "slim": "sha256:" + "e" * 64}
    verified.add(different["slim"])
    with pytest.raises(module.VerificationError, match="different digest"):
        module.publish_canonical(tmp_path, source, different)
    assert len(attempts) == 2


@pytest.mark.parametrize("readback", ["wrong-digest", "missing", "error"])
def test_canonical_publication_rejects_unverified_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, readback: str
) -> None:
    from types import SimpleNamespace

    module = _module(monkeypatch)
    monkeypatch.setattr(module, "verify_image", lambda *_args, **_kwargs: "a" * 40)
    monkeypatch.setattr(
        module,
        "_ghcr_digest_for_tag_once",
        lambda _tag: SimpleNamespace(status=module.TagLookupStatus.MISSING),
    )
    writes: list[list[str]] = []
    monkeypatch.setattr(module, "_run", lambda _repo, argv: writes.append(argv))
    statuses = {
        "wrong-digest": module.TagLookupStatus.FOUND,
        "missing": module.TagLookupStatus.MISSING,
        "error": module.TagLookupStatus.ERROR,
    }
    monkeypatch.setattr(
        module,
        "_ghcr_digest_for_tag",
        lambda _tag: SimpleNamespace(status=statuses[readback], digest="sha256:" + "f" * 64),
    )
    with pytest.raises(module.VerificationError, match="readback"):
        module.publish_canonical(
            tmp_path, "a" * 40, {"slim": "sha256:" + "b" * 64, "analyzers": "sha256:" + "c" * 64}
        )
    assert len(writes) == 1
