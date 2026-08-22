"""Refusal, recovery, and extraction paths in managed-binary provisioning (#431).

``tests/analyzers/test_provision.py`` covers the pinned happy path and
``tests/analyzers/test_provision_cache_integrity.py`` covers receipt verification
after a self-updating tool rewrites its binary. What neither drives is the set of
decisions that *refuse* work: an unpinned or redirected download URL, an archive
member that escapes its extraction directory, a cache entry that cannot be
purged, and the second cache check taken after another worker won the lock.

No test here reaches the network. ``_download_pinned_url`` is replaced with a
local write, and the two tests that exercise the downloader itself replace
``httpx.stream`` and the egress guards with in-memory fakes.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import ipaddress
import tarfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import provision
from mergecraft.analyzers.manifest import AnalyzerManifest
from mergecraft.security.egress import GuardedUrl, SsrfBlockedError

if TYPE_CHECKING:
    from collections.abc import Iterator

_PAYLOAD = b"#!/bin/sh\necho pinned-tool 1.0.0\n"
_PAYLOAD_SHA = hashlib.sha256(_PAYLOAD).hexdigest()
_PLATFORM = "linux-amd64"
_URL = "https://example.invalid/faketool"


def _manifest(*, url: str = _URL, sha256: str = _PAYLOAD_SHA, platform: str = _PLATFORM) -> Any:
    """Managed manifest whose pinned artifact is the fake binary."""
    return AnalyzerManifest.model_validate(
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
            "provenance": {platform: {"url": url, "sha256": sha256}},
            "network_allowlist": [],
        }
    )


@pytest.fixture
def fake_download(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the pinned download with a local write; return the call log."""
    calls: list[str] = []

    def _fake(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(_PAYLOAD)

    monkeypatch.setattr(provision, "_download_pinned_url", _fake)
    return calls


def _provision(cache_dir: Path, manifest: Any = None) -> Any:
    return provision.provision_managed_binary(
        manifest=manifest if manifest is not None else _manifest(),
        platform=_PLATFORM,
        cache_dir=cache_dir,
    )


# --- refusals before anything is fetched ---------------------------------------


def test_platform_without_provenance_is_refused_by_name() -> None:
    """A platform the manifest never pinned cannot be provisioned.

    Falling back to another platform's pin would install a binary for the wrong
    architecture and still report it as pinned.
    """
    with pytest.raises(provision.ProvisionError) as exc_info:
        provision.provision_managed_binary(
            manifest=_manifest(),
            platform="darwin-arm64",
            cache_dir=Path("/nonexistent-cache"),
        )

    message = str(exc_info.value)
    assert "darwin-arm64" in message
    assert "faketool" in message


def test_blank_sha256_pin_is_refused(tmp_path: Path, fake_download: list[str]) -> None:
    """A whitespace-only pin is treated as no pin at all.

    ``expected_sha256`` is stripped before use; without the emptiness check the
    cache key would be the empty string and ``_verify_sha256`` would compare
    against nothing, accepting any downloaded bytes.
    """
    with pytest.raises(provision.ProvisionError, match=r"non-empty sha256"):
        provision.provision_managed_binary(
            manifest=_manifest(),
            platform=_PLATFORM,
            cache_dir=tmp_path / "cache",
            expected_sha256="   ",
        )

    assert fake_download == []


def test_download_os_error_is_reported_as_a_provision_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filesystem failure while downloading surfaces as ``ProvisionError``.

    ``provision_managed_binary`` is the boundary the analyzer pipeline catches;
    a bare ``OSError`` escaping it would abort the whole run instead of marking
    one tool skipped.
    """

    def _explode(url: str, dest: Path) -> None:
        _ = (url, dest)
        msg = "No space left on device"
        raise OSError(msg)

    monkeypatch.setattr(provision, "_download_pinned_url", _explode)

    with pytest.raises(provision.ProvisionError, match=r"download failed for faketool"):
        _provision(tmp_path / "cache")


# --- receipts ------------------------------------------------------------------


def test_receipt_is_absent_for_a_directory_that_has_none(tmp_path: Path) -> None:
    """Reading a receipt from a directory without one returns ``None``, not an error."""
    assert provision.read_provision_receipt(tmp_path) is None


def test_receipt_content_is_normalised_and_validated(tmp_path: Path) -> None:
    """Only a bare 64-char hex digest counts as a receipt.

    The receipt decides whether a cached binary is executed. Accepting truncated
    or non-hex content would let a corrupt sidecar authorise an unverified file;
    accepting a partial match would let ``deadbeef…`` plus trailing junk through.
    """
    receipt = tmp_path / provision.RECEIPT_NAME

    receipt.write_text(f"{_PAYLOAD_SHA.upper()}\n", encoding="utf-8")
    assert provision.read_provision_receipt(tmp_path) == _PAYLOAD_SHA

    receipt.write_text("not-a-digest\n", encoding="utf-8")
    assert provision.read_provision_receipt(tmp_path) is None

    receipt.write_text(f"{_PAYLOAD_SHA} trailing\n", encoding="utf-8")
    assert provision.read_provision_receipt(tmp_path) is None

    receipt.write_text(f"{_PAYLOAD_SHA[:-1]}\n", encoding="utf-8")
    assert provision.read_provision_receipt(tmp_path) is None


def test_corrupt_receipt_forces_reprovisioning(tmp_path: Path, fake_download: list[str]) -> None:
    """An unreadable receipt is a cache miss, not a cache hit.

    A half-written sidecar (interrupted run, truncated volume) must send the
    caller back to the pin rather than serving a binary nothing vouches for.
    """
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    (first.resolved_path.parent / provision.RECEIPT_NAME).write_text("garbage", encoding="utf-8")

    second = _provision(cache_dir)

    assert second.source == "download"
    assert second.sha256 == _PAYLOAD_SHA
    assert fake_download == [_URL, _URL]


# --- cache purge ---------------------------------------------------------------


def test_purge_removes_directories_a_self_updating_tool_left_behind(
    tmp_path: Path, fake_download: list[str]
) -> None:
    """Re-provisioning drops sibling directories, not just the binary.

    TruffleHog's updater unpacks into a sibling directory. Leaving it in place
    would let stale updater state survive the purge and re-enter the next run.
    """
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    cache_root = first.resolved_path.parent
    stale_dir = cache_root / "updater-state"
    stale_dir.mkdir()
    (stale_dir / "manifest.json").write_text("stale", encoding="utf-8")
    first.resolved_path.write_bytes(b"#!/bin/sh\necho attacker 9.9.9\n")

    second = _provision(cache_dir)

    assert second.source == "download"
    assert not stale_dir.exists()
    assert second.resolved_path.read_bytes() == _PAYLOAD


def test_undeletable_cache_entry_is_refused_rather_than_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_download: list[str]
) -> None:
    """A purge that cannot complete raises instead of falling through.

    If the untrusted entry cannot be removed, provisioning must not continue and
    overwrite around it — the run would end up executing whatever survived.
    """
    cache_dir = tmp_path / "cache"
    first = _provision(cache_dir)
    stale_dir = first.resolved_path.parent / "updater-state"
    stale_dir.mkdir()
    first.resolved_path.write_bytes(b"#!/bin/sh\necho attacker 9.9.9\n")

    def _refuse(path: Any) -> None:
        _ = path
        msg = "Permission denied"
        raise OSError(msg)

    monkeypatch.setattr(provision.shutil, "rmtree", _refuse)

    with pytest.raises(provision.ProvisionError, match=r"failed to discard untrusted cache entry"):
        _provision(cache_dir)

    assert len(fake_download) == 1, "no second download after the purge failed"


# --- lock contention -----------------------------------------------------------


def test_entry_provisioned_while_waiting_for_the_lock_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_download: list[str]
) -> None:
    """The in-lock re-check serves the winner's binary instead of downloading again.

    Two workers can both miss the cache and queue on the lock. Without the second
    check the loser re-downloads and ``os.replace``s the file the winner may be
    executing. Here the lock helper stands in for the winning worker: it installs
    a verified entry before the caller's critical section begins.
    """
    cache_dir = tmp_path / "cache"
    cache_root = cache_dir / "faketool" / _PLATFORM / _PAYLOAD_SHA

    @contextlib.contextmanager
    def _lock_that_loses_the_race(root: Path) -> Iterator[None]:
        root.mkdir(parents=True, exist_ok=True)
        binary = root / "faketool"
        binary.write_bytes(_PAYLOAD)
        provision._write_provision_receipt(root, _PAYLOAD_SHA)
        yield

    monkeypatch.setattr(provision, "_cache_provision_lock", _lock_that_loses_the_race)

    result = _provision(cache_dir)

    assert result.source == "cache"
    assert result.sha256 == _PAYLOAD_SHA
    assert result.resolved_path == cache_root / "faketool"
    assert fake_download == [], "the loser of the lock race must not re-download"


# --- pinned download URL handling ----------------------------------------------


class _FakeResponse:
    """Minimal stand-in for the streamed ``httpx`` response."""

    def __init__(self, *, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            msg = f"HTTP {self.status_code}"
            raise httpx.HTTPError(msg)

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._body


@pytest.fixture
def scripted_http(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeResponse]:
    """Serve scripted responses by URL and neutralise DNS/egress pinning."""
    responses: dict[str, _FakeResponse] = {}
    localhost = ipaddress.ip_address("93.184.216.34")

    def _guard(url: str) -> GuardedUrl:
        from urllib.parse import urlparse

        return GuardedUrl(url=url, host=urlparse(url).hostname or "", addresses=(localhost,))

    @contextlib.contextmanager
    def _pin(host: str, addresses: Any) -> Iterator[None]:
        _ = (host, addresses)
        yield

    @contextlib.contextmanager
    def _stream(method: str, url: str, **kwargs: Any) -> Iterator[_FakeResponse]:
        _ = (method, kwargs)
        assert url in responses, f"unscripted request to {url}"
        yield responses[url]

    monkeypatch.setattr(provision, "inspect_external_url", _guard)
    monkeypatch.setattr(provision, "pin_host_resolution", _pin)
    monkeypatch.setattr(provision.httpx, "stream", _stream)
    return responses


@pytest.mark.parametrize(
    "url",
    ["http://example.invalid/faketool", "file:///etc/passwd", "https:///faketool"],
)
def test_non_https_or_hostless_download_url_is_refused(tmp_path: Path, url: str) -> None:
    """Only ``https://host/...`` is downloadable, and nothing is written.

    A plaintext or hostless URL defeats the pin: the bytes can be substituted in
    transit or read off the local filesystem.
    """
    dest = tmp_path / "artifact"

    with pytest.raises(provision.ProvisionError, match=r"unpinned or non-https"):
        provision._download_pinned_url(url, dest)

    assert not dest.exists()


def test_ssrf_blocked_url_is_reported_as_a_provision_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An SSRF verdict becomes a provisioning refusal with its reason intact.

    The egress guard's message names *why* the host was rejected; wrapping must
    not lose it, and ``SsrfBlockedError`` (a ``PermissionError``) must not escape
    to callers that only handle ``ProvisionError``.
    """

    def _blocked(url: str) -> GuardedUrl:
        _ = url
        msg = "host resolves to a link-local address"
        raise SsrfBlockedError(msg)

    monkeypatch.setattr(provision, "inspect_external_url", _blocked)

    with pytest.raises(provision.ProvisionError, match=r"link-local"):
        provision._download_pinned_url("https://metadata.invalid/x", tmp_path / "artifact")


def test_redirect_to_an_allowed_release_host_is_followed(
    tmp_path: Path, scripted_http: dict[str, _FakeResponse]
) -> None:
    """GitHub's release redirect to its asset CDN is followed and the body kept.

    Release downloads always 302 to ``objects.githubusercontent.com``; refusing
    that hop would make every managed analyzer unprovisionable.
    """
    asset = "https://objects.githubusercontent.com/faketool"
    scripted_http["https://github.invalid/faketool"] = _FakeResponse(
        status_code=302, headers={"location": asset}, body=b""
    )
    scripted_http[asset] = _FakeResponse(status_code=200, headers={}, body=_PAYLOAD)
    dest = tmp_path / "artifact"

    provision._download_pinned_url("https://github.invalid/faketool", dest)

    assert dest.read_bytes() == _PAYLOAD


def test_redirect_without_a_location_header_is_refused(
    tmp_path: Path, scripted_http: dict[str, _FakeResponse]
) -> None:
    """A 302 with no ``Location`` cannot be followed and must not silently pass.

    Treating it as success would leave an empty file that then fails the sha
    check with a confusing "mismatch" instead of the real cause.
    """
    scripted_http[_URL] = _FakeResponse(status_code=302, headers={}, body=b"")

    with pytest.raises(provision.ProvisionError, match=r"missing Location"):
        provision._download_pinned_url(_URL, tmp_path / "artifact")


def test_redirect_off_the_allowlist_is_refused_naming_the_original_url(
    tmp_path: Path, scripted_http: dict[str, _FakeResponse]
) -> None:
    """A redirect to an unrelated host is rejected, and the error names the pin.

    This is the hop an attacker controls once a release host is compromised or a
    URL is typo-squatted; the allowlist is what keeps the download on the CDN the
    pin was computed against.
    """
    scripted_http[_URL] = _FakeResponse(
        status_code=302, headers={"location": "https://evil.invalid/payload"}, body=b""
    )
    dest = tmp_path / "artifact"

    with pytest.raises(provision.ProvisionError) as exc_info:
        provision._download_pinned_url(_URL, dest)

    message = str(exc_info.value)
    assert _URL in message
    assert "https://evil.invalid/payload" in message
    assert not dest.exists()


def test_redirect_chain_is_bounded(tmp_path: Path, scripted_http: dict[str, _FakeResponse]) -> None:
    """A self-referential redirect terminates instead of looping forever.

    ``_download_pinned_url`` allows eight hops; a redirect to the same URL would
    otherwise hang the analyzer run rather than fail it.
    """
    scripted_http[_URL] = _FakeResponse(status_code=307, headers={"location": _URL}, body=b"")

    with pytest.raises(provision.ProvisionError, match=r"too many redirects"):
        provision._download_pinned_url(_URL, tmp_path / "artifact")


def test_http_error_during_download_is_wrapped_with_the_url(
    tmp_path: Path, scripted_http: dict[str, _FakeResponse]
) -> None:
    """A failing status becomes a ``ProvisionError`` naming the URL that failed."""
    scripted_http[_URL] = _FakeResponse(status_code=503, headers={}, body=b"")

    with pytest.raises(provision.ProvisionError, match=r"download failed for"):
        provision._download_pinned_url(_URL, tmp_path / "artifact")


# --- archive extraction ---------------------------------------------------------


def _tar_bytes(members: dict[str, bytes], *, mode: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _archive_for(artifact_name: str) -> bytes:
    """Build a one-binary archive in the format implied by ``artifact_name``."""
    if artifact_name.endswith((".tar.gz", ".tgz")):
        return _tar_bytes({"bin/faketool": _PAYLOAD}, mode="w:gz")
    if artifact_name.endswith((".tar.xz", ".txz")):
        return _tar_bytes({"bin/faketool": _PAYLOAD}, mode="w:xz")
    return _zip_bytes({"bin/": b"", "bin/faketool": _PAYLOAD})


@pytest.mark.parametrize(
    "artifact_name",
    ["faketool.tar.gz", "faketool.tgz", "faketool.tar.xz", "faketool.txz", "faketool.zip"],
)
def test_pinned_archive_is_unpacked_and_the_named_binary_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
) -> None:
    """Each supported archive format yields the manifest's binary, executable.

    The pin covers the *archive*, so the sha check runs on the download and the
    extracted file is what gets its own receipt. A format that fell through to
    the raw-file branch would install the compressed bytes as the executable.
    """
    archive = _archive_for(artifact_name)
    url = f"https://example.invalid/{artifact_name}"

    def _fake(download_url: str, dest: Path) -> None:
        _ = download_url
        dest.write_bytes(archive)

    monkeypatch.setattr(provision, "_download_pinned_url", _fake)
    manifest = _manifest(url=url, sha256=hashlib.sha256(archive).hexdigest())

    result = _provision(tmp_path / "cache", manifest)

    assert result.source == "download"
    assert result.resolved_path.read_bytes() == _PAYLOAD
    assert result.sha256 == _PAYLOAD_SHA
    assert result.resolved_path.stat().st_mode & 0o111


def test_zip_member_escaping_the_extraction_directory_is_refused(tmp_path: Path) -> None:
    """A ``../`` member is rejected before anything is written outside the dir.

    Zip-slip: the archive is attacker-influenced the moment a release host is
    compromised, and extraction runs with the review job's privileges.
    """
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"../escaped": _PAYLOAD}))
    dest_dir = tmp_path / "extract"
    dest_dir.mkdir()

    with pytest.raises(provision.ProvisionError, match=r"unsafe archive member path"):
        provision._extract_executable(archive, dest_dir, "faketool")

    assert not (tmp_path / "escaped").exists()


def test_archive_without_the_named_binary_falls_back_to_its_only_file(tmp_path: Path) -> None:
    """A release that renames the binary still resolves to the file it shipped.

    Upstream archives often carry ``faketool-linux-amd64``. Failing here would
    make the analyzer unavailable even though the pinned bytes are present.
    """
    archive = tmp_path / "faketool.zip"
    archive.write_bytes(_zip_bytes({"faketool-linux-amd64": _PAYLOAD}))
    dest_dir = tmp_path / "extract"
    dest_dir.mkdir()

    extracted = provision._extract_executable(archive, dest_dir, "faketool")

    assert extracted.name == "faketool-linux-amd64"
    assert extracted.read_bytes() == _PAYLOAD


def test_empty_archive_is_refused(tmp_path: Path) -> None:
    """An archive with no files is an error, not an empty install."""
    archive = tmp_path / "faketool.zip"
    archive.write_bytes(_zip_bytes({}))
    dest_dir = tmp_path / "extract"
    dest_dir.mkdir()

    with pytest.raises(provision.ProvisionError, match=r"no executable found in archive"):
        provision._extract_executable(archive, dest_dir, "faketool")


def test_non_archive_artifact_is_installed_verbatim(tmp_path: Path) -> None:
    """A bare binary download is copied under the manifest's command name."""
    artifact = tmp_path / "faketool"
    artifact.write_bytes(_PAYLOAD)
    dest_dir = tmp_path / "staging"
    dest_dir.mkdir()

    staged = provision._extract_executable(artifact, dest_dir, "faketool")

    assert staged == dest_dir / "faketool"
    assert staged.read_bytes() == _PAYLOAD


# --- lockfile resolution --------------------------------------------------------


def test_lock_entries_for_other_tools_are_ignored(tmp_path: Path, fake_download: list[str]) -> None:
    """A lock recording another tool does not satisfy this manifest.

    ``read_lock`` returns every entry in the file. Matching on anything but the
    tool id would resolve ``faketool`` to whatever sha the neighbouring entry
    happens to carry.
    """
    from mergecraft.analyzers.lockfile import LockEntry, read_lock, write_lock

    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    write_lock(
        lock_path,
        [
            LockEntry(
                tool_id="othertool",
                version="9.9.9",
                mode="managed",
                source="cache",
                sha256="0" * 64,
            )
        ],
    )

    result = provision.resolve_with_lock(
        manifest=_manifest(),
        lock_path=lock_path,
        cache_dir=tmp_path / "cache",
        platform=_PLATFORM,
    )

    assert result.source == "download"
    assert result.sha256 == _PAYLOAD_SHA
    assert fake_download == [_URL]
    assert {entry.tool_id for entry in read_lock(lock_path)} == {"othertool", "faketool"}


def test_locked_tool_without_provenance_for_the_platform_is_refused(tmp_path: Path) -> None:
    """A lock entry cannot stand in for a missing platform pin.

    The lock records a sha but no URL. Serving from it when the manifest has no
    provenance for this platform would mean trusting a digest with nothing to
    fetch or re-verify it against.
    """
    from mergecraft.analyzers.lockfile import LockEntry, write_lock

    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    write_lock(
        lock_path,
        [
            LockEntry(
                tool_id="faketool",
                version="1.0.0",
                mode="managed",
                source="cache",
                sha256=_PAYLOAD_SHA,
            )
        ],
    )

    with pytest.raises(provision.ProvisionError, match=r"no provenance for platform"):
        provision.resolve_with_lock(
            manifest=_manifest(),
            lock_path=lock_path,
            cache_dir=tmp_path / "cache",
            platform="darwin-arm64",
        )


# --- baked image resolution ------------------------------------------------------


def test_baked_binary_is_ignored_outside_the_full_analyzers_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``MERGECRAFT_ANALYZERS=full`` nothing on the host is trusted.

    Resolving a same-named binary from the developer's ``PATH`` would run an
    unpinned tool in place of the managed one.
    """
    baked = tmp_path / "analyzers"
    baked.mkdir()
    (baked / "faketool").write_bytes(_PAYLOAD)
    monkeypatch.setattr(provision, "BAKED_ANALYZER_ROOT", baked)
    monkeypatch.delenv("MERGECRAFT_ANALYZERS", raising=False)

    assert provision.resolve_baked_binary(_manifest()) is None

    monkeypatch.setenv("MERGECRAFT_ANALYZERS", "minimal")
    assert provision.resolve_baked_binary(_manifest()) is None


def test_baked_binary_is_used_in_the_full_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the full image the baked path wins, case- and space-insensitively."""
    baked = tmp_path / "analyzers"
    baked.mkdir()
    (baked / "faketool").write_bytes(_PAYLOAD)
    monkeypatch.setattr(provision, "BAKED_ANALYZER_ROOT", baked)
    monkeypatch.setenv("MERGECRAFT_ANALYZERS", "  FULL ")

    assert provision.resolve_baked_binary(_manifest()) == baked / "faketool"


def test_full_image_falls_back_to_path_then_gives_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the baked path is empty, ``PATH`` is consulted, then ``None`` is returned.

    The fallback is what lets an apt/pip-installed analyzer serve the full image;
    returning a path when nothing was found would send an unrunnable command to
    the sandbox.
    """
    monkeypatch.setattr(provision, "BAKED_ANALYZER_ROOT", tmp_path / "empty")
    monkeypatch.setenv("MERGECRAFT_ANALYZERS", "full")

    on_path = tmp_path / "bin" / "faketool"
    on_path.parent.mkdir()
    on_path.write_bytes(_PAYLOAD)
    monkeypatch.setattr(provision.shutil, "which", lambda name: str(on_path))
    assert provision.resolve_baked_binary(_manifest()) == on_path

    monkeypatch.setattr(provision.shutil, "which", lambda name: None)
    assert provision.resolve_baked_binary(_manifest()) is None


def test_platform_key_matches_the_provenance_key_format() -> None:
    """The host platform key is the one manifests pin provenance under.

    It is also a cache-path component, so a drifting format would silently
    re-download every analyzer on every run.
    """
    from mergecraft.analyzers.execution import provision_platform_key

    key = provision.platform_key()

    assert key == provision_platform_key()
    assert key.split("-")[0] in {"linux", "darwin", "windows"}
    assert key.split("-")[1] in {"amd64", "arm64"}
