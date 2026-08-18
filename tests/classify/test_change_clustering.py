"""DG2 change clustering — dependency and intent groups (G6).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG2).
Implementation: **DG2.2** — cluster large diffs by dependency and intent; feed
the split advisor.
"""

from __future__ import annotations

from typing import Any


def _change(*paths: str, **signals: object) -> dict[str, object]:
    return {"changed_paths": list(paths), "diff_stats": signals}


def _cluster_change(change: dict[str, object], **kwargs: Any) -> Any:
    from mergecraft.classify.change_clustering import cluster_changes

    return cluster_changes(change, **kwargs)


def test_files_cluster_by_dependency_and_intent() -> None:
    """Related files cluster together; unrelated paths land in separate groups."""
    change = _change(
        "src/api/handlers.py",
        "src/api/routes.py",
        "src/billing/invoice.py",
        "docs/guide.md",
        files_changed=4,
    )
    dependency_edges = [
        ("src/api/routes.py", "src/api/handlers.py"),
    ]
    intents = {
        "src/api/handlers.py": "api-refactor",
        "src/api/routes.py": "api-refactor",
        "src/billing/invoice.py": "billing-fix",
        "docs/guide.md": "docs-only",
    }

    result = _cluster_change(change, dependency_edges=dependency_edges, intents=intents)

    cluster_for = {path: group.id for group in result.clusters for path in group.paths}
    assert cluster_for["src/api/handlers.py"] == cluster_for["src/api/routes.py"]
    assert cluster_for["src/billing/invoice.py"] != cluster_for["src/api/handlers.py"]
    assert cluster_for["docs/guide.md"] != cluster_for["src/billing/invoice.py"]


def test_independent_groups_are_identified() -> None:
    """Wholly unrelated change groups are surfaced for the split advisor."""
    change = _change(
        "frontend/app.tsx",
        "frontend/router.tsx",
        "infra/terraform/main.tf",
        "infra/terraform/variables.tf",
        files_changed=4,
    )
    dependency_edges = [
        ("frontend/app.tsx", "frontend/router.tsx"),
        ("infra/terraform/main.tf", "infra/terraform/variables.tf"),
    ]
    intents = {
        "frontend/app.tsx": "ui",
        "frontend/router.tsx": "ui",
        "infra/terraform/main.tf": "infra",
        "infra/terraform/variables.tf": "infra",
    }

    result = _cluster_change(change, dependency_edges=dependency_edges, intents=intents)

    assert len(result.independent_groups) >= 2
    group_paths = [frozenset(group.paths) for group in result.independent_groups]
    assert frozenset({"frontend/app.tsx", "frontend/router.tsx"}) in group_paths
    assert frozenset({"infra/terraform/main.tf", "infra/terraform/variables.tf"}) in group_paths
