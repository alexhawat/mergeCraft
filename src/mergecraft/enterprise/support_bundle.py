"""Support bundles with secret redaction for enterprise deployments (#381).

Distinct from ``mergecraft.reliability.diagnostic_bundle``.

Exports:
    write_support_bundle: Write a gzipped tar archive, redacting secrets.
"""

from __future__ import annotations

import io
import re
import sys
import tarfile
from pathlib import Path

__all__ = [
    "write_support_bundle",
]

_ARCHIVE_SUFFIXES = {".tgz", ".tar.gz", ".tar"}

_SECRET_PATTERNS = [
    # API-key-style tokens (sk-..., ghp_..., etc.)
    re.compile(r"(?i)(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36,}|xox[baprs]-[^\s]+)"),
    # Bearer tokens
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]{10,}"),
    # Generic key=value secrets
    re.compile(r"(?i)(password|token|secret|api[_-]?key)\s*=\s*\S+"),
]


def _redact(text: str) -> str:
    """Replace secret material in *text* with ``[REDACTED]``."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def write_support_bundle(destination: Path, *, extra_text: str = "") -> str:
    """Write a gzipped tar support bundle to *destination*, redacting secrets.

    Args:
        destination: Output path.  Must end with ``.tgz``, ``.tar.gz``, or
            ``.tar``.  Parent directories are created automatically.
        extra_text: Optional additional text to include in the bundle.

    Returns:
        The string form of the written *destination* path.

    Raises:
        ValueError: When *destination* does not have a recognised archive suffix.
    """
    dest = Path(destination)
    suffix_lower = "".join(dest.suffixes).lower()
    if dest.suffix.lower() not in {".tgz", ".tar"} and not suffix_lower.endswith(".tar.gz"):
        msg = f"bundle destination must be a .tgz / .tar.gz archive, got: {dest.name!r}"
        raise ValueError(msg)

    dest.parent.mkdir(parents=True, exist_ok=True)

    python_info = f"python: {sys.version}\nplatform: {sys.platform}\n"
    extra_redacted = _redact(extra_text) if extra_text else ""

    manifest = "# mergeCraft support bundle\n" + python_info
    if extra_redacted:
        manifest += "\n# Extra info\n" + extra_redacted + "\n"

    with tarfile.open(dest, "w:gz") as archive:
        _add_text(archive, "manifest.txt", manifest)

    return str(dest)


def _add_text(archive: tarfile.TarFile, name: str, content: str) -> None:
    """Add *content* as a text file named *name* to *archive*."""
    encoded = content.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(encoded)
    archive.addfile(info, io.BytesIO(encoded))
