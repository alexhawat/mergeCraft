"""Automatic diagnostic bundles with secrets redacted (#365).

Exports:
    write_diagnostic_bundle: Write a ``.tgz`` that never contains secret material.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from mergecraft.analyzers.redact import redact_secrets


def write_diagnostic_bundle(path: Path, *, extra_text: str = "") -> Path:
    """Write a gzipped tarball for operators; secret-like strings are stripped.

    Args:
        path: Destination ``.tgz`` path.
        extra_text: Optional operator notes; redacted before archive.

    Returns:
        The path written.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = redact_secrets(extra_text).encode("utf-8")
    info = tarfile.TarInfo(name="diagnostics.txt")
    info.size = len(payload)
    with tarfile.open(destination, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))
    return destination
