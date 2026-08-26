"""Support bundles with secret redaction for enterprise deployments (#381).

Distinct from ``mergecraft.reliability.diagnostic_bundle``.

Exports:
    write_support_bundle: Write a tar archive, redacting secrets.
"""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path
from typing import Literal

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.enterprise.audit import resolve_audit_log_path, verify_audit_chain
from mergecraft.reliability.diagnostic_bundle import write_diagnostic_bundle

__all__ = [
    "write_support_bundle",
]


def _archive_mode(destination: Path) -> Literal["w", "w:gz"]:
    """Return tarfile open mode from *destination* suffix (``.tar`` is uncompressed)."""
    suffix_lower = "".join(destination.suffixes).lower()
    if destination.suffix.lower() == ".tgz" or suffix_lower.endswith(".tar.gz"):
        return "w:gz"
    if destination.suffix.lower() == ".tar":
        return "w"
    msg = f"bundle destination must be a .tgz / .tar.gz / .tar archive, got: {destination.name!r}"
    raise ValueError(msg)


def write_support_bundle(
    destination: Path,
    *,
    extra_text: str = "",
    root: Path | None = None,
) -> str:
    """Write a support bundle to *destination*, redacting secrets.

    Args:
        destination: Output path.  Must end with ``.tgz``, ``.tar.gz``, or
            ``.tar``.  Parent directories are created automatically.
        extra_text: Optional additional text to include in the bundle.
        root: Workspace root used to resolve the audit log path. Defaults to
            the current working directory when omitted — callers must run from
            the intended workspace (or pass ``root`` explicitly).

    Returns:
        The string form of the written *destination* path.

    Raises:
        ValueError: When *destination* does not have a recognised archive suffix.
    """
    dest = Path(destination)
    mode = _archive_mode(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    python_info = f"python: {sys.version}\nplatform: {sys.platform}\n"
    payload = python_info
    audit_path = resolve_audit_log_path(root=root)
    if audit_path.is_file():
        breaks = verify_audit_chain(audit_path)
        payload += f"audit_log: {audit_path}\n"
        if breaks:
            payload += f"audit_chain_breaks: {breaks}\n"
        else:
            payload += "audit_chain: ok\n"
    if extra_text:
        payload += "\n# Extra info\n" + extra_text + "\n"

    if mode == "w:gz":
        write_diagnostic_bundle(dest, extra_text=payload)
        return str(dest)

    encoded = redact_secrets(payload).encode("utf-8")
    info = tarfile.TarInfo(name="diagnostics.txt")
    info.size = len(encoded)
    with tarfile.open(dest, "w") as archive:
        archive.addfile(info, io.BytesIO(encoded))
    return str(dest)
