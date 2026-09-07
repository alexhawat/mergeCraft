"""Unit tests for ``scripts/check_action_image_digest.py`` (#526)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT


def _load_module() -> Any:
    path = REPO_ROOT / "scripts" / "check_action_image_digest.py"
    spec = importlib.util.spec_from_file_location("check_action_image_digest", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stub_manifest_head(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    digest: str | None = None,
    http_error: int | None = None,
) -> None:
    """Stub the registry HEAD so status classification is tested, not the network."""
    monkeypatch.setattr(module, "_ghcr_pull_token", lambda: "stub-token")

    class _Response:
        def __init__(self) -> None:
            self.headers = {"docker-content-digest": digest}

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def _urlopen(request: object, timeout: int = 30) -> _Response:
        if http_error is not None:
            raise urllib.error.HTTPError(
                url="https://ghcr.io", code=http_error, msg="stub", hdrs=None, fp=None
            )
        return _Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", _urlopen)


class TestGhcrDigestLookup:
    """Status classification, stubbed at the HTTP boundary.

    These once queried GHCR directly and asserted a hardcoded digest. That put
    an assertion about mutable external state in the unit tier: the jobs running
    them do not depend on ``action-slim-bootstrap``, so a tag pushed moments
    earlier read as MISSING and failed the run. What belongs here is the
    parsing contract; live parity is the checker's own job in CI.
    """

    def test_a_digest_header_is_reported_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = _load_module()
        digest = "sha256:" + "a" * 64
        _stub_manifest_head(module, monkeypatch, digest=digest)

        lookup = module._ghcr_digest_for_tag("b34e9f25c5d2dee0e638fa3c62f29733d0fc10c5")

        assert lookup.status == module.TagLookupStatus.FOUND
        assert lookup.digest == digest

    def test_404_is_missing_not_a_registry_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MISSING and ERROR drive different outcomes; 404 must not look like a fault."""
        module = _load_module()
        _stub_manifest_head(module, monkeypatch, http_error=404)
        monkeypatch.setattr(module, "_MISSING_RETRIES", 0)

        lookup = module._ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.MISSING

    def test_500_is_a_registry_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = _load_module()
        _stub_manifest_head(module, monkeypatch, http_error=500)

        lookup = module._ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.ERROR

    def test_a_missing_tag_is_retried_then_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A push GHCR has not surfaced yet must be retried, not failed outright."""
        module = _load_module()
        digest = "sha256:" + "b" * 64
        calls: list[int] = []

        def _flaky(tag: str) -> object:
            calls.append(1)
            if len(calls) < 3:
                return module.TagLookupResult(status=module.TagLookupStatus.MISSING)
            return module.TagLookupResult(status=module.TagLookupStatus.FOUND, digest=digest)

        monkeypatch.setattr(module, "_ghcr_digest_for_tag_once", _flaky)
        monkeypatch.setattr(module, "_MISSING_BACKOFF_SECONDS", 0)

        lookup = module._ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.FOUND
        assert lookup.digest == digest
        assert len(calls) == 3

    def test_retries_are_bounded_so_an_unpublished_sha_still_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Retry must not turn a genuinely absent image into a stalled job."""
        module = _load_module()
        calls: list[int] = []

        def _always_missing(tag: str) -> object:
            calls.append(1)
            return module.TagLookupResult(status=module.TagLookupStatus.MISSING)

        monkeypatch.setattr(module, "_ghcr_digest_for_tag_once", _always_missing)
        monkeypatch.setattr(module, "_MISSING_RETRIES", 2)
        monkeypatch.setattr(module, "_MISSING_BACKOFF_SECONDS", 0)

        lookup = module._ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.MISSING
        assert len(calls) == 3

    def test_a_registry_error_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ERROR will not resolve itself in seconds; retrying only delays the caller."""
        module = _load_module()
        calls: list[int] = []

        def _always_error(tag: str) -> object:
            calls.append(1)
            return module.TagLookupResult(status=module.TagLookupStatus.ERROR)

        monkeypatch.setattr(module, "_ghcr_digest_for_tag_once", _always_error)
        monkeypatch.setattr(module, "_MISSING_BACKOFF_SECONDS", 0)

        lookup = module._ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.ERROR
        assert len(calls) == 1

    def test_an_image_without_the_tracing_extra_is_detected(self) -> None:
        module = _load_module()
        config = {"config": {"Env": ["PATH=/usr/bin"]}, "history": [{"created_by": "RUN uv sync"}]}

        assert module._image_has_tracing_extra(config) is False


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=30, check=True
    )
    return result.stdout.strip()


def _history(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Release Fixture")
    action = repo / "action.yml"
    action.write_text(
        "runs:\n  using: docker\n  image: docker://ghcr.io/alexhawat/mergecraft@sha256:"
        + "a" * 64
        + "\n"
    )
    (repo / "runtime.py").write_text("VALUE = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: source fixture")
    source = _git(repo, "rev-parse", "HEAD")
    action.write_text(action.read_text().replace("a" * 64, "b" * 64))
    _git(repo, "commit", "-am", "test: manifest fixture")
    return repo, source, _git(repo, "rev-parse", "HEAD")


def _config(source: str) -> dict[str, Any]:
    return {
        "config": {"Labels": {"org.opencontainers.image.revision": source}},
        "history": [{"created_by": "RUN uv sync --extra tracing"}],
    }


def test_manifest_only_commit_verifies_actual_pinned_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    repo, source, manifest = _history(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr(
        module, "_fetch_oci_config_for_tag", lambda digest: seen.append(digest) or _config(source)
    )
    monkeypatch.setattr(module, "_verify_attestations", lambda *args: None)
    # Uncommitted working-tree bytes must never change what uses@C executes.
    (repo / "action.yml").write_text("runs:\n  image: Dockerfile\n")
    result = module.verify_manifest(repo, manifest)
    assert result.source_revision == source
    assert result.manifest_commit == manifest
    assert result.image_digest == "sha256:" + "b" * 64
    assert seen == [result.image_digest]


def test_correct_worktree_cannot_rescue_old_pinned_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    repo, source, _manifest = _history(tmp_path)
    monkeypatch.setattr(
        module,
        "_fetch_oci_config_for_tag",
        lambda digest: _config(source) if digest.endswith("b" * 64) else None,
    )
    with pytest.raises(module.VerificationError, match="registry"):
        module.verify_manifest(repo, source)


@pytest.mark.parametrize("change", ["runtime", "entrypoint", "args", "workflow"])
def test_manifest_must_not_change_runtime_or_build_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    module = _load_module()
    repo, source, _manifest = _history(tmp_path)
    if change == "runtime":
        (repo / "runtime.py").write_text("VALUE = 2\n")
    elif change == "workflow":
        (repo / "release.yml").write_text("unreviewed workflow\n")
    else:
        with (repo / "action.yml").open("a") as stream:
            stream.write(f"  {change}: changed\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: changed behavior")
    monkeypatch.setattr(module, "_fetch_oci_config_for_tag", lambda _: _config(source))
    monkeypatch.setattr(module, "_verify_attestations", lambda *args: None)
    with pytest.raises(module.VerificationError, match="changes"):
        module.verify_manifest(repo, _git(repo, "rev-parse", "HEAD"))


@pytest.mark.parametrize(
    "failure", ["missing-revision", "wrong-revision", "missing-tracing", "registry", "attestation"]
)
def test_image_claims_do_not_bypass_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    module = _load_module()
    config = _config("a" * 40)
    if failure == "missing-revision":
        config["config"]["Labels"] = {}
    elif failure == "wrong-revision":
        config["config"]["Labels"][module.OCI_REVISION_LABEL] = "b" * 40
    elif failure == "missing-tracing":
        config["history"] = [{"created_by": "RUN uv sync"}]
    monkeypatch.setattr(
        module, "_fetch_oci_config_for_tag", lambda _: None if failure == "registry" else config
    )

    def deny(*args: object) -> None:
        raise module.VerificationError("attestation rejected")

    monkeypatch.setattr(module, "_verify_attestations", deny)
    with pytest.raises(module.VerificationError):
        module.verify_image(tmp_path, "sha256:" + "d" * 64, "a" * 40)


def test_attestation_commands_bind_digest_source_and_trusted_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "_run", lambda repo, argv: calls.append(argv) or "")
    digest, source = "sha256:" + "b" * 64, "a" * 40
    module._verify_attestations(tmp_path, digest, source)
    assert len(calls) == 3
    for argv in calls[:2]:
        assert argv[:4] == ["gh", "attestation", "verify", f"oci://{module.SLIM_IMAGE}@{digest}"]
        assert argv[argv.index("--source-digest") + 1] == source
        assert argv[argv.index("--signer-digest") + 1] == source
        assert "--signer-workflow" not in argv
        assert argv[argv.index("--repo") + 1] == "alexhawat/mergeCraft"
        assert "--deny-self-hosted-runners" in argv
        identity = argv[argv.index("--cert-identity-regex") + 1]
        assert module.re.fullmatch(
            identity,
            "https://github.com/alexhawat/mergeCraft/.github/workflows/ci-cd.yml@refs/heads/main",
        )
        assert not module.re.fullmatch(
            identity,
            "https://github.com/alexhawat/mergeCraft/.github/workflows/ci-cd.yml@refs/pull/42/merge",
        )
    assert calls[1][-2:] == ["--predicate-type", "https://spdx.dev/Document"]
    assert calls[2][-1] == f"{module.SLIM_IMAGE}@{digest}"
    assert "--certificate-oidc-issuer" in calls[2]


def test_offline_is_explicitly_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    repo, _source, manifest = _history(tmp_path)
    monkeypatch.setattr(module, "REPO", repo)
    assert module.main(["--offline", "--manifest-commit", manifest]) == 2
    assert "UNVERIFIED" in capsys.readouterr().out


@pytest.mark.parametrize("image", ["Dockerfile", "docker://ghcr.io/alexhawat/mergecraft:latest"])
def test_source_structure_rejects_unpinned_image(tmp_path: Path, image: str) -> None:
    module = _load_module()
    action = tmp_path / "action.yml"
    action.write_text(f"runs:\n  image: {image}\n")
    module.ACTION_YML = action
    assert module.main(["--structure-only"]) == 1


@pytest.mark.parametrize("tamper", [False, True])
def test_registry_config_is_bound_to_immutable_descriptor_hashes(
    monkeypatch: pytest.MonkeyPatch, tamper: bool
) -> None:
    import hashlib
    import json

    module = _load_module()
    objects: dict[str, bytes] = {}

    def store(value: dict[str, Any]) -> str:
        raw = json.dumps(value).encode()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        objects[digest] = raw
        return digest

    config = _config("a" * 40)
    config_digest = store(config)
    manifest = store({"config": {"digest": config_digest}})
    index = store(
        {"manifests": [{"digest": manifest, "platform": {"os": "linux", "architecture": "amd64"}}]}
    )
    if tamper:
        objects[config_digest] = json.dumps(_config("b" * 40)).encode()
    monkeypatch.setattr(module, "_ghcr_pull_token", lambda: "public-fixture")

    class Response:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.data

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout: Response(objects[request.full_url.rsplit("/", 1)[1]]),
    )
    result = module._fetch_oci_config_for_tag(index)
    assert result == (None if tamper else config)


def test_real_gh_accepts_attestation_policy_before_offline_bundle_failure(tmp_path: Path) -> None:
    """Exercise gh's real argument parser without registry access or mocked execution."""
    import os
    import shutil

    gh = shutil.which("gh")
    if gh is None:
        pytest.skip("gh CLI required for real attestation argument compatibility")
    module = _load_module()
    artifact = tmp_path / "artifact"
    artifact.write_text("public parser fixture\n")
    missing = tmp_path / "missing-bundle.jsonl"
    result = subprocess.run(
        [
            gh,
            "attestation",
            "verify",
            str(artifact),
            "--bundle",
            str(missing),
            *module._attestation_policy("a" * 40),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "GH_TOKEN": "public-parser-fixture",
            "HTTPS_PROXY": "http://127.0.0.1:1",
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    downstream_error = (
        "missing-bundle.jsonl" in result.stderr
        and "no such file or directory" in result.stderr.lower()
    ) or "no valid Sigstore verifiers could be initialized" in result.stderr
    assert downstream_error, result.stderr
    assert "were all set" not in result.stderr
    assert "unknown flag" not in result.stderr


def test_candidate_image_change_verifies_full_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    repo, source, manifest = _history(tmp_path)
    monkeypatch.setattr(module, "verify_image", lambda *_args: source)
    result = module.verify_candidate(repo, source, manifest)
    assert result["manifests"][0]["manifest_commit"] == manifest
    action = repo / "action.yml"
    action.write_text(action.read_text() + "  entrypoint: malicious\n")
    _git(repo, "commit", "-am", "test: incompatible manifest")
    with pytest.raises(module.VerificationError, match="behavior"):
        module.verify_candidate(repo, source, _git(repo, "rev-parse", "HEAD"))


def test_source_metadata_can_build_but_cannot_be_pinned_without_matching_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    repo, source, manifest = _history(tmp_path)
    monkeypatch.setattr(module, "verify_image", lambda *_args: source)
    action = repo / "action.yml"
    action.write_text(action.read_text() + "  args: [changed]\n")
    _git(repo, "commit", "-am", "test: source metadata")
    changed = _git(repo, "rev-parse", "HEAD")
    assert module.verify_candidate(repo, manifest, changed)["state"] == "source-only-change"
    workflow = repo / ".github/workflows/review.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(f"jobs:\n  review:\n    uses: alexhawat/mergeCraft@{changed}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: deploy incompatible candidate")
    with pytest.raises(module.VerificationError, match="behavior"):
        module.verify_candidate(repo, changed, _git(repo, "rev-parse", "HEAD"))


def test_candidate_rejects_mutable_new_pin_but_allows_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    repo, source, manifest = _history(tmp_path)
    monkeypatch.setattr(module, "verify_image", lambda *_args: source)
    workflow = repo / ".github/workflows/review.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("jobs:\n  review:\n    uses: alexhawat/mergeCraft@main\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "test: mutable reference")
    mutable = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(module.VerificationError):
        module.verify_candidate(repo, manifest, mutable)
    workflow.write_text(f"env:\n  MERGECRAFT_ACTION_SHA: {manifest}\n")
    _git(repo, "commit", "-am", "test: repair mutable reference")
    result = module.verify_candidate(repo, mutable, _git(repo, "rev-parse", "HEAD"))
    assert result["manifests"][0]["manifest_commit"] == manifest
    with pytest.raises(module.VerificationError):
        module.verify_candidate(repo, "main", manifest)
