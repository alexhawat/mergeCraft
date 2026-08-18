"""Change clustering for large PRs — dependency and intent groups (DG2, G6).

Groups changed paths so hierarchical summarization and the split advisor can
treat related edits together while surfacing wholly independent work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChangeCluster:
    """One cluster of related changed paths."""

    id: str
    paths: list[str] = field(default_factory=list)
    intent: str | None = None


@dataclass(slots=True)
class ClusterResult:
    """Clustering output for summarization and split advice."""

    clusters: list[ChangeCluster] = field(default_factory=list)
    independent_groups: list[ChangeCluster] = field(default_factory=list)


def _union_find(parent: dict[str, str], path: str) -> str:
    if parent[path] != path:
        parent[path] = _union_find(parent, parent[path])
    return parent[path]


def _union(parent: dict[str, str], left: str, right: str) -> None:
    root_left = _union_find(parent, left)
    root_right = _union_find(parent, right)
    if root_left != root_right:
        parent[root_right] = root_left


def _connected_components(
    paths: list[str],
    dependency_edges: list[tuple[str, str]],
) -> list[list[str]]:
    path_set = set(paths)
    parent = {path: path for path in paths}
    for left, right in dependency_edges:
        if left in path_set and right in path_set:
            _union(parent, left, right)
    components: dict[str, list[str]] = {}
    for path in paths:
        root = _union_find(parent, path)
        components.setdefault(root, []).append(path)
    return [sorted(group) for group in components.values()]


def _cluster_id(intent: str | None, paths: list[str]) -> str:
    if intent:
        return intent
    if len(paths) == 1:
        return paths[0]
    return "+".join(paths[:2])


def cluster_changes(
    change: dict[str, Any],
    *,
    dependency_edges: list[tuple[str, str]] | None = None,
    intents: dict[str, str] | None = None,
) -> ClusterResult:
    """Group changed paths by dependency edges and declared intent.

    Args:
        change: Side-effect-free change payload with ``changed_paths``.
        dependency_edges: Directed dependency pairs among changed paths.
        intents: Optional per-path intent labels.

    Returns:
        :class:`ClusterResult` with ``clusters`` and ``independent_groups``.
    """
    paths = list(change.get("changed_paths") or [])
    if not paths:
        return ClusterResult()

    edges = dependency_edges or []
    intent_map = intents or {}

    components = _connected_components(paths, edges)
    clusters: list[ChangeCluster] = []
    independent_groups: list[ChangeCluster] = []

    for component in components:
        has_internal_edge = any(left in component and right in component for left, right in edges)
        by_intent: dict[str, list[str]] = {}
        for path in component:
            intent = intent_map.get(path, "unclassified")
            by_intent.setdefault(intent, []).append(path)

        if len(by_intent) == 1:
            intent, group_paths = next(iter(by_intent.items()))
            cluster = ChangeCluster(
                id=_cluster_id(None if intent == "unclassified" else intent, group_paths),
                paths=sorted(group_paths),
                intent=None if intent == "unclassified" else intent,
            )
            clusters.append(cluster)
        else:
            for intent, group_paths in sorted(by_intent.items()):
                clusters.append(
                    ChangeCluster(
                        id=_cluster_id(None if intent == "unclassified" else intent, group_paths),
                        paths=sorted(group_paths),
                        intent=None if intent == "unclassified" else intent,
                    )
                )

        if has_internal_edge and len(component) >= 2:
            dominant_intent = intent_map.get(component[0])
            independent_groups.append(
                ChangeCluster(
                    id=_cluster_id(dominant_intent, component),
                    paths=sorted(component),
                    intent=dominant_intent,
                )
            )
        elif len(component) == 1:
            path = component[0]
            path_intent = intent_map.get(path, "unclassified")
            other_intents = {
                intent_map.get(other_path, "unclassified")
                for other_path in paths
                if other_path != path
            }
            if path_intent not in other_intents:
                independent_groups.append(
                    ChangeCluster(
                        id=_cluster_id(
                            None if path_intent == "unclassified" else path_intent,
                            component,
                        ),
                        paths=sorted(component),
                        intent=None if path_intent == "unclassified" else path_intent,
                    )
                )

    return ClusterResult(clusters=clusters, independent_groups=independent_groups)


__all__ = ["ChangeCluster", "ClusterResult", "cluster_changes"]
