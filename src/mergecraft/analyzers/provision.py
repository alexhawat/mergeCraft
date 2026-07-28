"""Pinned managed-binary provisioning (D10)."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from loguru import logger

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


def _safe_archive_member_path(dest_dir: Path, member_name: str) -> Path:
    dest_root = dest_dir.resolve()
    target = (dest_root / member_name).resolve()
    if target != dest_root and dest_root not in target.parents:
        msg = f"unsafe archive member path: {member_name!r}"
        raise ProvisionError(msg)
    return target


def _download_pinned_url(url: str, dest: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        msg = f"refusing unpinned or non-https download url: {url!r}"
        raise ProvisionError(msg)
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        msg = f"download failed for {url!r}: {exc}"
        raise ProvisionError(msg) from exc


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
    lock_path = cache_root / ".provision.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if sys.platform != "win32":
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform != "win32":
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _install_cached_binary(*, staged: Path, cached: Path) -> None:
    cached.parent.mkdir(parents=True, exist_ok=True)
    staging = cached.with_name(f".{cached.name}.staging")
    staging.write_bytes(staged.read_bytes())
    staging.chmod(staging.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(staging, cached)


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
        binary_sha = _sha256_file(cached)
        return ProvisionResult(
            resolved_path=cached,
            sha256=binary_sha,
            version=manifest.version,
            source="cache",
        )

    with _cache_provision_lock(cache_root):
        if cached.is_file():
            binary_sha = _sha256_file(cached)
            return ProvisionResult(
                resolved_path=cached,
                sha256=binary_sha,
                version=manifest.version,
                source="cache",
            )

        logger.info("provisioning {} {} from pinned url", manifest.id, platform)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_name = entry.url.rsplit("/", 1)[-1]
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

            _install_cached_binary(staged=staged, cached=cached)

    binary_sha = _sha256_file(cached)
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
    """Provision using lockfile for reproducibility (D24)."""
    from mergecraft.analyzers.lockfile import LockEntry, read_lock, write_lock

    for entry in read_lock(lock_path):
        if entry.tool_id != manifest.id:
            continue
        provenance_pin = manifest.provenance.get(platform)
        if provenance_pin is None:
            break
        cache_file = (
            _cache_path(cache_dir, manifest.id, platform, provenance_pin.sha256)
            / manifest.command[0]
        )
        if cache_file.is_file() and _sha256_file(cache_file) == entry.sha256:
            return ProvisionResult(
                resolved_path=cache_file,
                sha256=entry.sha256,
                version=entry.version,
                source=entry.source,
            )

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


__all__ = [
    "BAKED_ANALYZER_ROOT",
    "ProvisionError",
    "ProvisionResult",
    "fetch_unpinned",
    "provision_managed_binary",
    "resolve_baked_binary",
    "resolve_with_lock",
]
