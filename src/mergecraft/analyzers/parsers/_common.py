"""Shared helpers for analyzer output parsers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import unquote, urlparse

from mergecraft.analyzers.manifest import ManifestValidationError
from mergecraft.review_taxonomy import FINDING_CATEGORIES

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mergecraft.analyzers.manifest import AnalyzerManifest

_MANIFEST_CATEGORY_TO_TAXONOMY: dict[str, str] = {
    "ci": "Security & Privacy",
    "lint": "Maintainability & Code Quality",
    "security": "Security & Privacy",
    "vuln": "Security & Privacy",
    "secrets": "Security & Privacy",
    "contract": "Functional Correctness",
    "migration": "Data Integrity & Atomicity",
}

_CONFIDENCE_ALIASES: dict[str, str] = {
    "certain": "certain",
    "high": "likely",
    "medium": "likely",
    "low": "possible",
    "likely": "likely",
    "possible": "possible",
    "verified": "likely",
    "unverified": "possible",
}


def taxonomy_category(manifest: AnalyzerManifest) -> str:
    """Map manifest category shorthand to a review_taxonomy category."""
    if manifest.category in FINDING_CATEGORIES:
        return manifest.category
    mapped = _MANIFEST_CATEGORY_TO_TAXONOMY.get(manifest.category)
    if mapped is not None:
        return mapped
    return "Maintainability & Code Quality"


def map_native_severity(manifest: AnalyzerManifest, native_level: str) -> str:
    """Map a tool-native severity through the manifest severity_map (D2)."""
    mapped = manifest.severity_map.get(native_level)
    if mapped is None:
        msg = (
            f"unmapped native severity {native_level!r} for parser {manifest.parser!r} "
            f"on analyzer {manifest.id!r}"
        )
        raise ManifestValidationError(msg)
    return mapped


def map_confidence(reported: str | None) -> str:
    """Map analyzer-reported precision to FINDING_CONFIDENCES; default possible (D2)."""
    if reported is None:
        return "possible"
    normalized = reported.strip().casefold()
    mapped = _CONFIDENCE_ALIASES.get(normalized)
    if mapped is None:
        return "possible"
    return mapped


def resolve_repo_relative_path(
    uri: str,
    *,
    repo_root: Path | None = None,
    uri_base_id: str | None = None,
) -> str:
    """Resolve SARIF artifactLocation URIs to repo-relative paths."""
    cleaned = uri.strip()
    if cleaned.startswith("file://"):
        parsed = urlparse(cleaned)
        path = unquote(parsed.path)
        if repo_root is not None:
            try:
                return Path(path).resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                return Path(path).name
        return path.lstrip("/")

    path_obj = Path(cleaned)
    if repo_root is not None and path_obj.is_absolute():
        try:
            return path_obj.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            pass

    if uri_base_id in {"%SRCROOT%", "SRCROOT"} and repo_root is not None:
        return (repo_root / cleaned).resolve().relative_to(repo_root.resolve()).as_posix()

    if cleaned.startswith("./"):
        return cleaned[2:]
    return cleaned


def try_load_json(raw: str) -> object | None:
    """Return the first JSON value in ``raw``, or ``None`` when none parse."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            payload, _end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            continue
        return cast("object", payload)  # json.JSONDecoder.raw_decode is typed Any
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return cast("object", json.loads(stripped))  # json.loads is typed Any
    except json.JSONDecodeError:
        return None


def iter_json_objects(raw: str) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from JSONL (or a single object/array) without raising."""
    stripped = raw.strip()
    if not stripped:
        return
    yielded = False
    for line in raw.splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            yielded = True
            yield item
    if yielded:
        return
    loaded = try_load_json(stripped)
    if isinstance(loaded, dict):
        yield loaded
        return
    if isinstance(loaded, list):
        for item in loaded:
            if isinstance(item, dict):
                yield item


def coerce_line(value: object, *, default: int = 1) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(value, 1)
    if isinstance(value, float):
        return max(int(value), 1)
    if isinstance(value, str):
        try:
            return max(int(value.strip()), 1)
        except ValueError:
            return default
    return default
