"""Shared helpers for analyzer output parsers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from mergecraft.analyzers.manifest import ManifestValidationError
from mergecraft.review_taxonomy import FINDING_CATEGORIES
from mergecraft.utils.json_load import try_load_json, try_load_json_array, try_load_json_object

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

# Evidence label for a SARIF URI that cannot be mapped into the repository root.
OUTSIDE_REPO_ROOT_LABEL = "outside repository root"


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
    path, _outside = resolve_path_and_origin(uri, repo_root=repo_root, uri_base_id=uri_base_id)
    return path


def resolve_path_and_origin(
    uri: str,
    *,
    repo_root: Path | None = None,
    uri_base_id: str | None = None,
) -> tuple[str, bool]:
    """Resolve a SARIF URI to ``(path, outside_repo_root)``.

    A URI that maps into ``repo_root`` becomes repo-relative and reports
    ``False``. A URI outside the root — whether a ``file://`` URL or a bare
    absolute path — keeps its original form and reports ``True``. It is never
    shortened to a basename: the basename of an out-of-root path can name a
    real, unrelated file at the repo root, so a shortened path looks like an
    answer that cannot be anchored. A ``%SRCROOT%`` URI that escapes the root
    stays a rejection whose error names the URI (fail-closed).
    """
    cleaned = uri.strip()
    if cleaned.startswith("file://"):
        parsed = urlparse(cleaned)
        path = unquote(parsed.path)
        if repo_root is not None:
            relative = _relative_to_root(Path(path), repo_root)
            if relative is not None:
                return relative, False
            return cleaned, True
        return path.lstrip("/"), False

    path_obj = Path(cleaned)
    if repo_root is not None and path_obj.is_absolute():
        relative = _relative_to_root(path_obj, repo_root)
        if relative is not None:
            return relative, False
        return cleaned, True

    if uri_base_id in {"%SRCROOT%", "SRCROOT"} and repo_root is not None:
        try:
            resolved = (repo_root / cleaned).resolve().relative_to(repo_root.resolve())
        except ValueError:
            msg = f"SARIF URI {cleaned!r} (uriBaseId {uri_base_id!r}) escapes the repository root"
            raise ValueError(msg) from None
        return resolved.as_posix(), False

    if cleaned.startswith("./"):
        return cleaned[2:], False
    return cleaned, False


def _relative_to_root(path: Path, repo_root: Path) -> str | None:
    """Return ``path`` relative to ``repo_root``, or ``None`` when it escapes."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def load_json(raw: str) -> object:
    """Parse JSON from ``raw`` or raise ``ValueError``.

    A valid empty document (``[]`` / ``{}``) is returned as-is. Tool error
    text, argparse noise, and other non-JSON stdout must not look like a
    clean scan.
    """
    payload = try_load_json(raw)
    if payload is None:
        msg = "expected JSON object or array"
        raise ValueError(msg)
    return payload


def require_json_object(raw: str, *, what: str) -> dict[str, Any]:
    """Parse ``raw`` as a JSON object or raise ``ValueError``.

    Leading JSON arrays are skipped (same resume-at-``_end`` path as
    ``try_load_json_object``) so progress tokens cannot hide a later object.
    """
    payload = try_load_json_object(raw)
    if payload is None:
        msg = f"{what} must be a JSON object"
        raise ValueError(msg)
    return payload


def require_json_array(raw: str, *, what: str) -> list[Any]:
    """Parse ``raw`` as a JSON array or raise ``ValueError``.

    Progress-token objects may precede the array (same resume-at-``_end``
    path as ``try_load_json_array``). Other leading objects — including
    ``{"error": ...}`` — fail parse so they cannot hide a later ``[]``.
    """
    payload = try_load_json_array(raw)
    if payload is None:
        msg = f"{what} must be a JSON array"
        raise ValueError(msg)
    return payload


def require_diagnostic_text(raw: str, *, matched: bool, what: str) -> None:
    """Raise when non-empty stdout matched no diagnostic lines."""
    if raw.strip() and not matched:
        msg = f"{what} output is not in the expected diagnostic format"
        raise ValueError(msg)


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
        if loaded and not all(isinstance(item, dict) for item in loaded):
            return
        for item in loaded:
            if isinstance(item, dict):
                yield item


def load_jsonl_objects(raw: str) -> list[dict[str, Any]]:
    """Return JSON objects from JSONL (or a JSON array/object), else raise.

    Empty stdout is a valid empty document. Non-JSON tool error text is not.
    A JSON array of non-dicts is not an empty document.
    """
    stripped = raw.strip()
    if not stripped:
        return []
    parsed = list(iter_json_objects(raw))
    if parsed:
        return parsed
    payload = try_load_json(raw)
    if payload is None:
        msg = "expected JSONL objects"
        raise ValueError(msg)
    if payload in ({}, []):
        return []
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                msg = "expected JSONL objects"
                raise ValueError(msg)
            rows.append(item)
        return rows
    msg = "expected JSONL objects"
    raise ValueError(msg)


def _as_int_line(value: object) -> int:
    """Parse a line number from a tool payload, or raise ``ValueError``."""
    if isinstance(value, bool):
        msg = f"invalid line number: {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            msg = f"invalid line number: {value!r}"
            raise ValueError(msg) from None
    msg = f"invalid line number: {value!r}"
    raise ValueError(msg)


def coerce_line(value: object, *, default: int = 1) -> int:
    """Return a 1-based line number, mapping unusable values to ``default``."""
    if value is None:
        return max(default, 1)
    try:
        return max(_as_int_line(value), 1)
    except ValueError:
        return max(default, 1)


def require_line(value: object, *, default: int = 1) -> int:
    """Return a 1-based line number, or raise ``ValueError`` if unusable.

    ``None`` still maps to ``default`` (missing region). Invalid types and
    non-numeric strings fail closed.
    """
    if value is None:
        return max(default, 1)
    return max(_as_int_line(value), 1)


def coerce_optional_line(value: object) -> int | None:
    """Return a 1-based line, or ``None`` when the tool did not report one."""
    if value is None:
        return None
    try:
        parsed = _as_int_line(value)
    except ValueError:
        return None
    return parsed if parsed >= 1 else None
