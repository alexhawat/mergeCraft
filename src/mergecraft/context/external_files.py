"""Trust-tiered external context files with type, size, and provenance (#357).

External files are data, never merged into the standing instruction bundle.
Does not author mergeCraft's own AGENTS.md / skill (file 7).

Module: mergecraft.context.external_files
Depends: dataclasses, hashlib

Exports:
    Classes:
        ExternalContextFile — Loaded file with trust tier and provenance.
    Functions:
        load_external_context_file — Enforce suffix, size, trust, and provenance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExternalContextFile:
    """One operator-supplied context file with trust and provenance."""

    path: str
    trust_tier: str
    text: str
    provenance: dict[str, str]


def load_external_context_file(
    path: Path,
    *,
    trust_tier: str,
    max_bytes: int,
    allowed_suffixes: Sequence[str],
) -> ExternalContextFile:
    """Load ``path`` if its type, size, and trust classification are allowed."""
    suffix = path.suffix.casefold()
    allowed = {item.casefold() for item in allowed_suffixes}
    if suffix not in allowed:
        msg = f"external context file type {suffix!r} is not allowed"
        raise TypeError(msg)
    size = path.stat().st_size
    if size > max_bytes:
        msg = f"external context file exceeds max_bytes={max_bytes}"
        raise ValueError(msg)
    raw = path.read_bytes()
    if b"\x00" in raw:
        msg = "external context file must be text, not binary"
        raise ValueError(msg)
    text = raw.decode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    provenance = {
        "path": str(path),
        "sha256": digest,
        "trust_tier": trust_tier,
        "bytes": str(size),
    }
    return ExternalContextFile(
        path=str(path),
        trust_tier=trust_tier,
        text=text,
        provenance=provenance,
    )


__all__ = ["ExternalContextFile", "load_external_context_file"]
