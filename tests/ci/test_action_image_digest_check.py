"""Unit tests for ``scripts/check_action_image_digest.py`` (#526)."""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    import pytest


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

        lookup = module.ghcr_digest_for_tag("b34e9f25c5d2dee0e638fa3c62f29733d0fc10c5")

        assert lookup.status == module.TagLookupStatus.FOUND
        assert lookup.digest == digest

    def test_404_is_missing_not_a_registry_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MISSING and ERROR drive different outcomes; 404 must not look like a fault."""
        module = _load_module()
        _stub_manifest_head(module, monkeypatch, http_error=404)
        monkeypatch.setattr(module, "_MISSING_RETRIES", 0)

        lookup = module.ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.MISSING

    def test_500_is_a_registry_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = _load_module()
        _stub_manifest_head(module, monkeypatch, http_error=500)

        lookup = module.ghcr_digest_for_tag("0" * 40)

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

        lookup = module.ghcr_digest_for_tag("0" * 40)

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

        lookup = module.ghcr_digest_for_tag("0" * 40)

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

        lookup = module.ghcr_digest_for_tag("0" * 40)

        assert lookup.status == module.TagLookupStatus.ERROR
        assert len(calls) == 1

    def test_an_image_without_the_tracing_extra_is_detected(self) -> None:
        module = _load_module()
        config = {"config": {"Env": ["PATH=/usr/bin"]}, "history": [{"created_by": "RUN uv sync"}]}

        assert module.image_has_tracing_extra(config) is False


class TestMain:
    def test_fails_when_image_is_dockerfile(self, tmp_path: Path) -> None:
        module = _load_module()
        action = tmp_path / "action.yml"
        action.write_text("runs:\n  using: docker\n  image: Dockerfile\n", encoding="utf-8")
        module.ACTION_YML = action
        assert module.main() != 0

    def test_fails_on_mutable_tag(self, tmp_path: Path) -> None:
        module = _load_module()
        action = tmp_path / "action.yml"
        action.write_text(
            "runs:\n  using: docker\n  image: docker://ghcr.io/alexhawat/mergecraft:latest\n",
            encoding="utf-8",
        )
        module.ACTION_YML = action
        assert module.main() != 0

    def test_fails_on_pre_tracing_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pinned pre-#531 digests must not pass the tracing-extra contract."""
        module = _load_module()
        action = tmp_path / "action.yml"
        action.write_text(
            "runs:\n  using: docker\n  image: "
            "docker://ghcr.io/alexhawat/mergecraft@"
            "sha256:955510ad23e1aa23d564475c2220ec0988236838a914a2a7472ea38220cb1f90\n",
            encoding="utf-8",
        )
        module.ACTION_YML = action
        monkeypatch.setattr(
            module,
            "_self_review_action_sha",
            lambda: "cfdf38dcd062779aac3e141c51f134213d395b67",
        )
        assert module.main() != 0

    def test_passes_on_repo_action_yml(self) -> None:
        module = _load_module()
        assert module.main() == 0
