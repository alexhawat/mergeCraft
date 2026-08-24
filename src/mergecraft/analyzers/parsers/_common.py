"""Shared helpers for analyzer output parsers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from mergecraft.analyzers.manifest import ManifestValidationError
from mergecraft.review_taxonomy import FINDING_CATEGORIES
from mergecraft.utils.json_load import try_load_json, try_load_json_object

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


def iter_bandit_result_rows(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield Bandit ``results`` objects, or raise on a missing/non-object row.

    Empty ``results: []`` is a clean scan. A missing array or a non-object
    row is a parse failure — same contract as ``bandit_to_sarif``.
    """
    results = payload.get("results")
    if not isinstance(results, list):
        msg = "bandit JSON output missing a results array"
        raise ValueError(msg)
    for item in results:
        if not isinstance(item, dict):
            msg = "bandit JSON results array contains a non-object row"
            raise ValueError(msg)
        yield item


def require_json_array(raw: str, *, what: str) -> list[Any]:
    """Parse ``raw`` as a JSON array or raise ``ValueError``."""
    payload = load_json(raw)
    if not isinstance(payload, list):
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
        for item in loaded:
            if isinstance(item, dict):
                yield item


def load_jsonl_objects(raw: str) -> list[dict[str, Any]]:
    """Return JSON objects from JSONL (or a JSON array/object), else raise.

    Empty stdout is a valid empty document. Non-JSON tool error text is not.
    """
    stripped = raw.strip()
    if not stripped:
        return []
    objects = list(iter_json_objects(raw))
    if objects:
        return objects
    payload = try_load_json(raw)
    if payload is None:
        msg = "expected JSONL objects"
        raise ValueError(msg)
    if payload in ({}, []):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    msg = "expected JSONL objects"
    raise ValueError(msg)


def coerce_line(value: object, *, default: int = 1) -> int:
    """Return a 1-based line number, mapping unusable values to ``default``."""
    return _line_number(value, default=default, fail_closed=False)


def require_line(value: object, *, default: int = 1) -> int:
    """Return a 1-based line number, or raise ``ValueError`` if unusable.

    ``None`` still maps to ``default`` (missing region). Invalid types and
    non-numeric strings fail closed.
    """
    return _line_number(value, default=default, fail_closed=True)


def _line_number(value: object, *, default: int, fail_closed: bool) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        if fail_closed:
            msg = f"invalid line number: {value!r}"
            raise ValueError(msg)
        return default
    if isinstance(value, int):
        return max(value, 1)
    if isinstance(value, float):
        return max(int(value), 1)
    if isinstance(value, str):
        try:
            return max(int(value.strip()), 1)
        except ValueError:
            if fail_closed:
                msg = f"invalid line number: {value!r}"
                raise ValueError(msg) from None
            return default
    if fail_closed:
        msg = f"invalid line number: {value!r}"
        raise ValueError(msg)
    return default


_BANDIT_NATIVE_LEVELS: dict[str, str] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "undefined": "undefined",
}


def bandit_native_severity(result: dict[str, Any]) -> str:
    """Normalize Bandit ``issue_severity`` for the parser and SARIF converter."""
    return _BANDIT_NATIVE_LEVELS.get(
        str(result.get("issue_severity") or "medium").casefold(), "medium"
    )


def bandit_row_span(result: dict[str, Any]) -> tuple[int, int]:
    """Return ``(start_line, end_line)`` from ``line_number`` / ``line_range``."""
    start = coerce_line(result.get("line_number"), default=1)
    line_range = result.get("line_range")
    if isinstance(line_range, list) and line_range:
        end = coerce_line(line_range[-1], default=start)
        return start, max(end, start)
    return start, start


def coerce_optional_line(value: object) -> int | None:
    """Return a 1-based line, or ``None`` when the tool did not report one."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float):
        parsed = int(value)
        return parsed if parsed >= 1 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed >= 1 else None
    return None
