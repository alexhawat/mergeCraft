"""Pinned managed-binary provisioning (D10)."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from mergecraft.security.egress import (
    SsrfBlockedError,
    inspect_external_url,
    pinned_http_transport,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mergecraft.analyzers.manifest import AnalyzerManifest


class ProvisionError(RuntimeError):
    """Raised when a managed binary cannot be provisioned safely."""


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    resolved_path: Path
    sha256: str
    version: str
    source: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sha256(path: Path, expected: str) -> None:
    actual = _sha256_file(path)
    if actual.lower() != expected.lower():
        msg = (
            f"sha256 mismatch for {path.name}: expected {expected}, got {actual} — "
            "refusing to execute unpinned binary"
        )
        raise ProvisionError(msg)


#: Sidecar recording the *archive* pin and the sha256 of the binary that was
#: actually installed into a sha-keyed cache directory. The directory key is the
#: archive pin, so it says nothing about the extracted binary once a tool rewrites
#: itself in place (e.g. TruffleHog's built-in updater). The receipt binds both
#: together: a cached binary is only reused when it still hashes to what we wrote
#: *and* the receipt names the pin this manifest pins.
RECEIPT_NAME = ".provisioned-sha256"

_PROVISION_LOCK_NAME = ".provision.lock"
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def _receipt_path(cache_root: Path) -> Path:
    return cache_root / RECEIPT_NAME


def _receipt_lines(cache_root: Path) -> list[str]:
    try:
        raw = _receipt_path(cache_root).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip().casefold() for line in raw.splitlines() if line.strip()]


def read_provision_receipt(cache_root: Path) -> str | None:
    """Return the recorded binary sha256 for a cache directory, or ``None``.

    Accepts both the pin-bound receipt this module writes (two lines: the
    artifact pin, then the binary digest) and a legacy single-digest sidecar.
    Legacy content is readable here but never satisfies
    :func:`_verified_cache_hit`, which requires the pin binding.
    """
    lines = _receipt_lines(cache_root)
    if len(lines) == 1:
        return lines[0] if _HEX64_RE.fullmatch(lines[0]) else None
    if len(lines) == 2 and all(_HEX64_RE.fullmatch(line) for line in lines):
        return lines[1]
    return None


def _read_bound_receipt(cache_root: Path) -> tuple[str, str] | None:
    """Return ``(artifact_pin, binary_sha256)`` when the receipt binds both.

    A legacy single-digest receipt, or anything else malformed, is not a bound
    receipt: it proves only that *some* binary was once installed under this key,
    not which pinned artifact it came from.
    """
    lines = _receipt_lines(cache_root)
    if len(lines) != 2 or not all(_HEX64_RE.fullmatch(line) for line in lines):
        return None
    return lines[0], lines[1]


def _write_provision_receipt(
    cache_root: Path, digest: str, *, artifact_pin: str | None = None
) -> None:
    """Record the artifact pin and the installed binary digest together.

    ``artifact_pin`` defaults to the cache directory's own name, which is the
    archive pin in the standard ``<cache>/<tool>/<platform>/<pin>`` layout.
    """
    pin = (artifact_pin or cache_root.name).strip().casefold()
    receipt = _receipt_path(cache_root)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    staging = receipt.with_name(f".{receipt.name}.staging")
    staging.write_text(f"{pin}\n{digest.casefold()}\n", encoding="utf-8")
    os.replace(staging, receipt)


def _verified_cache_hit(
    *, cached: Path, cache_root: Path, manifest_id: str, artifact_pin: str
) -> str | None:
    """Return the cached binary's sha256 when it still matches its bound receipt.

    Returns ``None`` when the cache entry is unusable — no pin-bound receipt
    (provisioned by an older mergeCraft, or the receipt was removed), a receipt
    bound to a different pin, or a digest that no longer matches. Callers must
    re-provision instead of executing the file.
    """
    bound = _read_bound_receipt(cache_root)
    if bound is None:
        logger.info(
            "no pin-bound provisioning receipt for cached {} binary at {} — "
            "re-provisioning from the pin",
            manifest_id,
            cached,
        )
        return None
    recorded_pin, recorded = bound
    expected_pin = artifact_pin.strip().casefold()
    if recorded_pin != expected_pin:
        logger.warning(
            "cached {} binary was provisioned from pin {} (expected {}) — "
            "discarding and re-provisioning from the pin",
            manifest_id,
            recorded_pin,
            expected_pin,
        )
        return None
    actual = _sha256_file(cached)
    if actual.casefold() != recorded:
        logger.warning(
            "cached {} binary changed after provisioning (recorded {}, found {}) — "
            "discarding and re-provisioning from the pin",
            manifest_id,
            recorded,
            actual,
        )
        return None
    return actual


def _purge_cache_entry(cache_root: Path) -> None:
    """Drop everything in a cache directory except the lock we hold."""
    for child in cache_root.iterdir():
        if child.name == _PROVISION_LOCK_NAME:
            continue
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            msg = f"failed to discard untrusted cache entry {child}: {exc}"
            raise ProvisionError(msg) from exc


def _safe_archive_member_path(dest_dir: Path, member_name: str) -> Path:
    dest_root = dest_dir.resolve()
    target = (dest_root / member_name).resolve()
    if target != dest_root and dest_root not in target.parents:
        msg = f"unsafe archive member path: {member_name!r}"
        raise ProvisionError(msg)
    return target


def _download_pinned_url(url: str, dest: Path) -> None:
    current = url
    client: httpx.Client | None = None
    transport_key = None
    try:
        for _ in range(8):
            parsed = urlparse(current)
            if parsed.scheme != "https" or not parsed.netloc:
                msg = f"refusing unpinned or non-https download url: {current!r}"
                raise ProvisionError(msg)
            initial_host = parsed.netloc.casefold()
            allowed_hosts = {
                initial_host,
                "objects.githubusercontent.com",
                "release-assets.githubusercontent.com",
            }
            try:
                guarded = inspect_external_url(current)
            except SsrfBlockedError as exc:
                raise ProvisionError(str(exc)) from exc
            next_key = (guarded.host, guarded.addresses)
            if client is None or transport_key != next_key:
                if client is not None:
                    client.close()
                client = httpx.Client(
                    transport=pinned_http_transport(guarded.host, guarded.addresses),
                    follow_redirects=False,
                    timeout=120.0,
                )
                transport_key = next_key
            try:
                with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            msg = f"redirect from pinned download url {current!r} missing Location"
                            raise ProvisionError(msg)
                        current = urljoin(current, location)
                        next_parsed = urlparse(current)
                        next_host = (next_parsed.hostname or "").casefold()
                        if next_parsed.scheme != "https" or next_host not in allowed_hosts:
                            msg = (
                                f"refusing redirect from pinned download url {url!r} to {current!r}"
                            )
                            raise ProvisionError(msg)
                        continue
                    response.raise_for_status()
                    with dest.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                    return
            except httpx.HTTPError as exc:
                msg = f"download failed for {current!r}: {exc}"
                raise ProvisionError(msg) from exc
    finally:
        if client is not None:
            client.close()
    msg = f"too many redirects for pinned download url: {url!r}"
    raise ProvisionError(msg)


def _cache_path(cache_dir: Path, manifest_id: str, platform: str, artifact_sha256: str) -> Path:
    return cache_dir / manifest_id / platform / artifact_sha256


def _looks_like_archive(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".tar.gz", ".tgz", ".tar.xz", ".txz", ".zip"))


def _extract_executable(archive: Path, dest_dir: Path, binary_name: str) -> Path:
    name_lower = archive.name.lower()
    if name_lower.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest_dir, filter="data")
    elif name_lower.endswith((".tar.xz", ".txz")):
        with tarfile.open(archive, "r:xz") as tar:
            tar.extractall(dest_dir, filter="data")
    elif name_lower.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                target = _safe_archive_member_path(dest_dir, info.filename)
                if info.is_dir() or info.filename.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        target = dest_dir / binary_name
        target.write_bytes(archive.read_bytes())
        return target

    candidates = sorted(dest_dir.rglob(binary_name))
    if not candidates:
        candidates = sorted(p for p in dest_dir.rglob("*") if p.is_file())
    if not candidates:
        msg = f"no executable found in archive {archive.name}"
        raise ProvisionError(msg)
    return candidates[0]


@contextlib.contextmanager
def _cache_provision_lock(cache_root: Path) -> Iterator[None]:
    """Serialize cache writes so parallel workers cannot clobber a running binary."""
    cache_root.mkdir(parents=True, exist_ok=True)
    lock_path = cache_root / _PROVISION_LOCK_NAME
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if sys.platform != "win32":
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform != "win32":
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _install_cached_binary(*, staged: Path, cached: Path, artifact_pin: str) -> str:
    """Install the staged binary into the cache and record its bound receipt."""
    cached.parent.mkdir(parents=True, exist_ok=True)
    staging = cached.with_name(f".{cached.name}.staging")
    staging.write_bytes(staged.read_bytes())
    staging.chmod(staging.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    digest = _sha256_file(staging)
    os.replace(staging, cached)
    _write_provision_receipt(cached.parent, digest, artifact_pin=artifact_pin)
    return digest


def fetch_unpinned(*, url: str, cache_dir: Path) -> None:
    """Unpinned downloads are forbidden (D10)."""
    _ = url, cache_dir
    msg = "unpinned fetch is not allowed — provenance.sha256 is required for every download"
    raise ProvisionError(msg)


def provision_managed_binary(
    *,
    manifest: AnalyzerManifest,
    platform: str,
    cache_dir: Path,
    expected_sha256: str | None = None,
) -> ProvisionResult:
    """Resolve a managed binary from cache or a pinned download."""
    entry = manifest.provenance.get(platform)
    if entry is None:
        msg = f"no provenance for platform {platform!r} on {manifest.id}"
        raise ProvisionError(msg)

    artifact_pin = (expected_sha256 or entry.sha256).strip()
    if not artifact_pin:
        msg = f"provenance[{platform!r}] requires a non-empty sha256 pin"
        raise ProvisionError(msg)

    binary_name = manifest.command[0]
    cache_root = _cache_path(cache_dir, manifest.id, platform, artifact_pin)
    cached = cache_root / binary_name
    if cached.is_file():
        verified = _verified_cache_hit(
            cached=cached,
            cache_root=cache_root,
            manifest_id=manifest.id,
            artifact_pin=artifact_pin,
        )
        if verified is not None:
            return ProvisionResult(
                resolved_path=cached,
                sha256=verified,
                version=manifest.version,
                source="cache",
            )

    with _cache_provision_lock(cache_root):
        if cached.is_file():
            verified = _verified_cache_hit(
                cached=cached,
                cache_root=cache_root,
                manifest_id=manifest.id,
                artifact_pin=artifact_pin,
            )
            if verified is not None:
                return ProvisionResult(
                    resolved_path=cached,
                    sha256=verified,
                    version=manifest.version,
                    source="cache",
                )
            # Never execute a binary we cannot tie back to the pin: drop the whole
            # entry (binary plus any updater state a self-updating tool left behind)
            # and fall through to a fresh pinned download.
            _purge_cache_entry(cache_root)

        logger.info("provisioning {} {} from pinned url", manifest.id, platform)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_name = entry.url.rsplit("/", 1)[-1]
            if not artifact_name:
                msg = (
                    f"provenance URL {entry.url} has no artifact filename "
                    "(trailing slash or empty last path segment)"
                )
                raise ProvisionError(msg)
            download_path = tmp_path / artifact_name
            try:
                _download_pinned_url(entry.url, download_path)
            except OSError as exc:
                msg = f"download failed for {manifest.id}: {exc}"
                raise ProvisionError(msg) from exc

            _verify_sha256(download_path, artifact_pin)

            if _looks_like_archive(artifact_name):
                extract_dir = tmp_path / "extract"
                extract_dir.mkdir()
                staged = _extract_executable(download_path, extract_dir, binary_name)
            else:
                staged = download_path

            binary_sha = _install_cached_binary(
                staged=staged, cached=cached, artifact_pin=artifact_pin
            )

    return ProvisionResult(
        resolved_path=cached,
        sha256=binary_sha,
        version=manifest.version,
        source="download",
    )


def resolve_with_lock(
    *,
    manifest: AnalyzerManifest,
    lock_path: Path,
    cache_dir: Path,
    platform: str,
) -> ProvisionResult:
    """Provision the managed binary and record the resolution in the lockfile.

    ``.mergecraft/analyzers.lock`` is a record, never an authenticator: it is
    still written (merged) so the pre-merge row can digest it, but nothing is
    ever served *from* it. A cached binary is only reused after the pin-bound
    receipt check inside :func:`provision_managed_binary`.
    """
    from mergecraft.analyzers.lockfile import LockEntry, write_lock

    result = provision_managed_binary(manifest=manifest, platform=platform, cache_dir=cache_dir)
    write_lock(
        lock_path,
        [
            LockEntry(
                tool_id=manifest.id,
                version=result.version,
                mode="managed",
                source=result.source,
                sha256=result.sha256,
            )
        ],
        merge=True,
    )
    return result


BAKED_ANALYZER_ROOT = Path("/usr/local/analyzers")


def resolve_baked_binary(manifest: AnalyzerManifest) -> Path | None:
    """Return a pre-baked binary path when running in the analyzers image (D10)."""
    if os.environ.get("MERGECRAFT_ANALYZERS", "").strip().lower() != "full":
        return None
    binary = manifest.command[0]
    candidate = BAKED_ANALYZER_ROOT / binary
    if candidate.is_file():
        return candidate
    discovered = shutil.which(binary)
    if discovered:
        return Path(discovered)
    return None


def platform_key() -> str:
    """Return the managed-binary platform key for this host."""
    from mergecraft.analyzers.execution import provision_platform_key

    return provision_platform_key()


__all__ = [
    "BAKED_ANALYZER_ROOT",
    "RECEIPT_NAME",
    "ProvisionError",
    "ProvisionResult",
    "fetch_unpinned",
    "platform_key",
    "provision_managed_binary",
    "read_provision_receipt",
    "resolve_baked_binary",
    "resolve_with_lock",
]
