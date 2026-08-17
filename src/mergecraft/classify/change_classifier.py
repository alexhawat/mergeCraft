"""Cheap change classifier producing a typed change/risk map (AP4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.classify.blast_radius import (
    BlastRadiusClassification,
    ChangeSet,
    RuleSet,
    classify_blast_radius,
)

if TYPE_CHECKING:
    from collections.abc import Callable

RiskBand = Literal["low", "medium", "high"]

_GENERATED_MARKERS = ("generated",)
_VENDORED_PREFIXES = ("vendor/", "third_party/")
_HIGH_STAKES_PATH_PARTS = (
    "auth",
    "billing",
    "payment",
    "payments",
    "security",
    "migration",
    "migrations",
    "permission",
    "permissions",
)
_SQL_TOKENS = ("alter table", "create table", "drop table", "insert into", "update ")


class ChangeClassification(BaseModel):
    """Typed classifier output intersected by lens routing."""

    model_config = ConfigDict(extra="forbid")

    risk_band: RiskBand
    blast_radius: BlastRadiusClassification
    change_map: dict[str, object]
    is_trivial: bool


def _path_lower(path: str) -> str:
    return path.lower().strip("/")


def _is_generated_path(path: str) -> bool:
    lowered = _path_lower(path)
    return any(part in lowered.split("/") for part in _GENERATED_MARKERS)


def _is_vendored_path(path: str) -> bool:
    lowered = _path_lower(path)
    return lowered.startswith(_VENDORED_PREFIXES)


def _diff_text(change: ChangeSet) -> str:
    stats = change.get("diff_stats", {})
    if not isinstance(stats, dict):
        return ""
    for key in ("diff", "diff_text", "patch", "text"):
        value = stats.get(key)
        if isinstance(value, str):
            return value.lower()
    return ""


def _stats_int(change: ChangeSet, key: str) -> int | None:
    stats = change.get("diff_stats", {})
    if not isinstance(stats, dict):
        return None
    value = stats.get(key)
    return value if isinstance(value, int) else None


def _is_doc_only_trivial(change: ChangeSet) -> bool:
    paths = [_path_lower(path) for path in change.get("changed_paths", [])]
    if not paths:
        return False
    if not all(
        path.endswith(".md") and (path.startswith("docs/") or "/docs/" in path) for path in paths
    ):
        return False
    if any(part in path for path in paths for part in _HIGH_STAKES_PATH_PARTS):
        return False
    if _diff_text(change) and any(token in _diff_text(change) for token in _SQL_TOKENS):
        return False
    files_changed = _stats_int(change, "files_changed")
    lines_added = _stats_int(change, "lines_added")
    lines_deleted = _stats_int(change, "lines_deleted")
    if files_changed is not None and files_changed > 1:
        return False
    return not (
        lines_added is not None and lines_deleted is not None and lines_added + lines_deleted > 4
    )


def _is_high_stakes_small_change(change: ChangeSet) -> bool:
    paths = [_path_lower(path) for path in change.get("changed_paths", [])]
    if any(part in path for path in paths for part in _HIGH_STAKES_PATH_PARTS):
        return True
    diff = _diff_text(change)
    return any(token in diff for token in _SQL_TOKENS)


def _infer_is_trivial(change: ChangeSet, blast_radius: BlastRadiusClassification) -> bool:
    paths = change.get("changed_paths", [])
    if not paths:
        return False
    if _is_high_stakes_small_change(change):
        return False
    if blast_radius.lane != "low":
        return False
    generated = [_path_lower(path) for path in paths if _is_generated_path(path)]
    if generated and len(generated) == len(paths):
        return True
    return _is_doc_only_trivial(change)


def classify_change(
    change: ChangeSet,
    *,
    rule_set: RuleSet | None = None,
    agent_runner: Callable[..., dict[str, object]] | None = None,
) -> ChangeClassification:
    """Classify ``change`` into a typed map; optional ``agent_runner`` runs once."""
    paths = list(change.get("changed_paths", []))
    blast_radius = classify_blast_radius(change, rule_set=rule_set)
    generated_paths = [path for path in paths if _is_generated_path(path)]
    vendored_paths = [path for path in paths if _is_vendored_path(path)]
    change_map: dict[str, object] = {
        "changed_paths": paths,
        "categories": list(blast_radius.categories),
        "generated_paths": generated_paths,
        "vendored_paths": vendored_paths,
    }
    is_trivial = _infer_is_trivial(change, blast_radius)
    if agent_runner is not None:
        agent_runner(change_payload=dict(change))
    return ChangeClassification(
        risk_band=blast_radius.lane,
        blast_radius=blast_radius,
        change_map=change_map,
        is_trivial=is_trivial,
    )


__all__ = [
    "ChangeClassification",
    "RiskBand",
    "classify_change",
]
