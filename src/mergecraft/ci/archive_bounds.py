"""Bounded zip archive reads for CI log and SARIF artifact ingestion (MCB-14)."""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

# 32 MiB aggregate / 8 MiB per member — large enough for real CI logs, small enough
# to bound attacker-controlled zip bombs on the review path.
_MAX_TOTAL_BYTES: Final[int] = 32 * 1024 * 1024
_MAX_MEMBER_BYTES: Final[int] = 8 * 1024 * 1024
_MAX_MEMBERS: Final[int] = 256
_MAX_RATIO: Final[int] = 200

_TRUNCATION_MARKER = "… <truncated>"


def _declared_amplification_exceeds_cap(infolist: list[zipfile.ZipInfo], raw_len: int) -> bool:
    if raw_len <= 0:
        return True
    declared = sum(info.file_size for info in infolist)
    return declared > raw_len * _MAX_RATIO


def _expansion_cap(raw_len: int) -> int:
    if raw_len <= 0:
        return 0
    return raw_len * _MAX_RATIO


def _decode_bounded_fallback(raw: bytes | bytearray) -> str:
    bounded = bytes(raw)[:_MAX_TOTAL_BYTES]
    text = bounded.decode("utf-8", errors="replace")
    if len(raw) > _MAX_TOTAL_BYTES:
        if text and not text.endswith(_TRUNCATION_MARKER):
            text = f"{text}\n{_TRUNCATION_MARKER}"
        elif not text:
            text = _TRUNCATION_MARKER
    return text


def _bounded_member_bytes(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    total_read: int,
    expansion_cap: int,
) -> tuple[bytes, bool]:
    with zf.open(info) as member:
        chunk = member.read(_MAX_MEMBER_BYTES + 1)
    truncated = len(chunk) > _MAX_MEMBER_BYTES
    if truncated:
        chunk = chunk[:_MAX_MEMBER_BYTES]

    remaining_total = _MAX_TOTAL_BYTES - total_read
    if len(chunk) > remaining_total:
        chunk = chunk[: max(remaining_total, 0)]
        truncated = True

    remaining_expansion = expansion_cap - total_read
    if len(chunk) > remaining_expansion:
        chunk = chunk[: max(remaining_expansion, 0)]
        truncated = True

    return chunk, truncated


def extract_zip_texts(
    raw: bytes | bytearray,
    *,
    name_filter: Callable[[str], bool],
) -> list[str]:
    """Extract filtered zip members with bounded decompression (D11)."""
    buffer = bytes(raw)
    with zipfile.ZipFile(BytesIO(buffer)) as zf:
        members = [info for info in zf.infolist() if name_filter(info.filename)]
        if _declared_amplification_exceeds_cap(members, len(buffer)):
            return [_TRUNCATION_MARKER]

        texts: list[str] = []
        total_read = 0
        expansion_cap = _expansion_cap(len(buffer))
        truncated = False

        for info in members[:_MAX_MEMBERS]:
            chunk, member_truncated = _bounded_member_bytes(
                zf,
                info,
                total_read=total_read,
                expansion_cap=expansion_cap,
            )
            if not chunk:
                if member_truncated:
                    truncated = True
                break

            total_read += len(chunk)
            text = chunk.decode("utf-8", errors="replace")
            if member_truncated:
                truncated = True
                text = f"{text}\n{_TRUNCATION_MARKER}"
            texts.append(text)
            if member_truncated:
                break

        if len(members) > _MAX_MEMBERS:
            truncated = True
        if truncated and (not texts or _TRUNCATION_MARKER not in texts[-1]):
            texts.append(_TRUNCATION_MARKER)
        return texts


def decode_log_archive(raw: bytes | bytearray) -> str:
    """Decode a GitHub Actions workflow log zip with bounded reads."""
    try:
        parts = extract_zip_texts(raw, name_filter=lambda name: name.endswith(".txt"))
    except zipfile.BadZipFile:
        return _decode_bounded_fallback(raw)
    if not parts:
        return ""
    return "\n".join(parts)


def extract_sarif_documents(raw: bytes | bytearray) -> list[str]:
    """Return SARIF documents from an artifact zip with bounded reads."""
    suffixes = (".sarif", ".sarif.json")

    def _is_sarif(name: str) -> bool:
        lowered = name.lower()
        return lowered.endswith(suffixes)

    return extract_zip_texts(raw, name_filter=_is_sarif)


__all__ = [
    "_MAX_MEMBERS",
    "_MAX_MEMBER_BYTES",
    "_MAX_RATIO",
    "_MAX_TOTAL_BYTES",
    "decode_log_archive",
    "extract_sarif_documents",
    "extract_zip_texts",
]
