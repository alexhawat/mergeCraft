"""Shared finding-id safety checks and evidence-packet lookup (#453).

Exports:
    is_safe_path_stem: Reject traversal and separator characters in file stems.
    load_json_packets_in_dir: Load ``*.json`` packets keyed by stem.
    lookup_packet_by_finding_id: Resolve a finding or short id against a packet map.
    fingerprint_for_short_id: Map ``MC-…`` back to a fingerprint in a batch.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from mergecraft.analyzers.finding import FINDING_SHORT_ID_PREFIX, resolve_finding_short_ids


def is_safe_path_stem(stem: str) -> bool:
    """Reject empty, ``..``, and separator characters so stems cannot escape a directory."""
    if not stem or stem in {".", ".."}:
        return False
    if "/" in stem or "\\" in stem:
        return False
    return Path(stem).parts == (stem,)


def load_json_packets_in_dir(
    directory: Path,
    *,
    skip_names: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    """Load ``*.json`` files in ``directory`` keyed by stem; skip corrupt files."""
    if not directory.is_dir():
        return {}
    packets: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name in skip_names:
            continue
        stem = path.stem
        if not is_safe_path_stem(stem):
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            packets[stem] = loaded
    return packets


def _nested_packet_candidates(packet: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield per-finding packets nested inside an aggregate evidence packet."""
    for key in ("packets", "evidence", "finding_packets"):
        nested = packet.get(key)
        if not isinstance(nested, dict):
            continue
        for value in nested.values():
            if isinstance(value, dict):
                yield value
    findings = packet.get("findings")
    if isinstance(findings, list):
        for row in findings:
            if isinstance(row, dict):
                yield row


def _fingerprints_in_packet_map(
    packets_by_fingerprint: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Collect fingerprint ids from packet keys and nested aggregate rows."""
    seen: set[str] = set()
    ordered: list[str] = []
    for stem, packet in packets_by_fingerprint.items():
        if stem and stem not in seen:
            seen.add(stem)
            ordered.append(stem)
        nested_id = str(packet.get("finding_id", "")).strip()
        if nested_id and nested_id not in seen:
            seen.add(nested_id)
            ordered.append(nested_id)
        for nested in _nested_packet_candidates(packet):
            fingerprint = str(nested.get("fingerprint", "")).strip()
            if not fingerprint:
                fingerprint = str(nested.get("finding_id", "")).strip()
            if fingerprint and fingerprint not in seen:
                seen.add(fingerprint)
                ordered.append(fingerprint)
    return tuple(ordered)


@lru_cache(maxsize=128)
def _short_id_index(fingerprints_tuple: tuple[str, ...]) -> dict[str, str]:
    """Memoized short-id → fingerprint map for one fingerprint batch."""
    mapping = resolve_finding_short_ids(fingerprints_tuple)
    return {short_id: fingerprint for fingerprint, short_id in mapping.items()}


def fingerprint_for_short_id(short_id: str, fingerprints: tuple[str, ...]) -> str | None:
    """Return the fingerprint for ``MC-…`` when it maps uniquely in ``fingerprints``."""
    if not short_id.startswith(FINDING_SHORT_ID_PREFIX):
        return None
    suffix = short_id[len(FINDING_SHORT_ID_PREFIX) :]
    if not suffix or not all(char in "0123456789abcdef" for char in suffix):
        return None
    return _short_id_index(tuple(sorted(fingerprints))).get(short_id)


def lookup_packet_by_finding_id(
    finding_id: str,
    packets_by_fingerprint: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a fingerprint or ``MC-…`` id against an in-memory packet map."""
    fingerprint_batch = _fingerprints_in_packet_map(packets_by_fingerprint)
    if finding_id.startswith(FINDING_SHORT_ID_PREFIX):
        fingerprint = fingerprint_for_short_id(finding_id, fingerprint_batch)
        if fingerprint is None:
            return None
        direct = packets_by_fingerprint.get(fingerprint)
        if direct is not None:
            return direct
        finding_id = fingerprint
    if not is_safe_path_stem(finding_id):
        return None
    direct = packets_by_fingerprint.get(finding_id)
    if direct is not None:
        return direct
    for packet in packets_by_fingerprint.values():
        if str(packet.get("finding_id", "")) == finding_id:
            return packet
        for nested in _nested_packet_candidates(packet):
            nested_id = str(nested.get("finding_id", "")).strip()
            nested_fp = str(nested.get("fingerprint", "")).strip()
            if finding_id in {nested_id, nested_fp}:
                return nested
    return None


__all__ = [
    "fingerprint_for_short_id",
    "is_safe_path_stem",
    "load_json_packets_in_dir",
    "lookup_packet_by_finding_id",
]
