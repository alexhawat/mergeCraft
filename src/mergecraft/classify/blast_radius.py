"""Pure blast-radius classification for merge evidence (#48)."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

Lane = Literal["low", "medium", "high"]
AutoMergeLane = Literal["eligible", "assisted", "human_review", "forbidden"]
Category = Literal[
    "migrations",
    "auth_security_payment",
    "secrets_config_deployment",
    "generated_files",
    "public_api_changes",
    "dependency_changes",
    "source_without_tests",
    "irreversible_infra",
]


class ChangeSet(TypedDict, total=False):
    """Side-effect-free change payload fed to the classifier."""

    changed_paths: list[str]
    diff_stats: dict[str, object]


class RuleOverride(TypedDict, total=False):
    """Per-category rule values that a repository may override."""

    lane: Lane


class RuleSet(TypedDict, total=False):
    """Additive per-repository blast-radius rule overrides."""

    migrations: RuleOverride
    auth_security_payment: RuleOverride
    secrets_config_deployment: RuleOverride
    generated_files: RuleOverride
    public_api_changes: RuleOverride
    dependency_changes: RuleOverride
    source_without_tests: RuleOverride
    irreversible_infra: RuleOverride


class BlastRadiusClassification(BaseModel):
    """Deterministic lane decision and the signals that produced it."""

    model_config = ConfigDict(extra="forbid")

    lane: Lane
    auto_merge_lane: AutoMergeLane
    reason: str
    next_action: str
    categories: list[str]


DEFAULT_RULE_SET: dict[Category, RuleOverride] = {
    "migrations": {"lane": "high"},
    "auth_security_payment": {"lane": "high"},
    "secrets_config_deployment": {"lane": "high"},
    "generated_files": {"lane": "low"},
    "public_api_changes": {"lane": "medium"},
    "dependency_changes": {"lane": "medium"},
    "source_without_tests": {"lane": "medium"},
    "irreversible_infra": {"lane": "high"},
}

_LANE_RANK: dict[Lane, int] = {"low": 0, "medium": 1, "high": 2}
_AUTO_MERGE_LANE: dict[Lane, AutoMergeLane] = {
    "low": "eligible",
    "medium": "assisted",
    "high": "forbidden",
}
_NEXT_ACTION: dict[Lane, str] = {
    "low": "Eligible for automatic merge after required checks pass.",
    "medium": "Use assisted review and verify the affected behavior.",
    "high": "Require human review; automatic merge is forbidden.",
}
_DEPENDENCY_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "poetry.lock",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
}
_DIFF_SIGNAL_KEYS = ("diff", "diff_text", "patch", "text")


def _contains_path_part(path: str, parts: tuple[str, ...]) -> bool:
    normalized = f"/{path.lower().strip('/')}"
    return any(f"/{part}/" in f"{normalized}/" for part in parts)


def _diff_text(diff_stats: dict[str, object]) -> str:
    return "\n".join(
        value for key in _DIFF_SIGNAL_KEYS if isinstance((value := diff_stats.get(key)), str)
    ).lower()


def _detected_categories(paths: list[str], diff_text: str) -> tuple[list[str], set[Category]]:
    categories: list[str] = []
    rule_categories: set[Category] = set()

    def add(rule_category: Category, *labels: str) -> None:
        rule_categories.add(rule_category)
        for label in labels or (rule_category,):
            if label not in categories:
                categories.append(label)

    lowered = [path.lower().strip("/") for path in paths]
    if any(_contains_path_part(path, ("migration", "migrations")) for path in lowered) or any(
        token in diff_text for token in ("drop table", "alter table", "create table")
    ):
        add("migrations")

    for path in lowered:
        if _contains_path_part(path, ("auth",)):
            add("auth_security_payment", "auth_security_payment", "auth")
        if _contains_path_part(path, ("security",)):
            add("auth_security_payment", "auth_security_payment", "security")
        if _contains_path_part(path, ("payment", "payments", "billing")):
            add("auth_security_payment", "auth_security_payment", "payment")
        if _contains_path_part(path, ("permission", "permissions")):
            add("auth_security_payment", "auth_security_payment", "permissions")

    secret_diff = any(
        token in diff_text
        for token in ("password =", "aws_secret_access_key", "secret_key =", "private_key =")
    )
    config_path = any(
        path == ".env.example" or path.startswith(("config/", ".github/workflows/"))
        for path in lowered
    )
    if secret_diff or config_path:
        labels = ["secrets_config_deployment"]
        if any(path.startswith(".github/workflows/") for path in lowered):
            labels.append("deployment")
        if any(path.startswith("config/") or path == ".env.example" for path in lowered):
            labels.append("secrets_config")
        add("secrets_config_deployment", *labels)

    if any(_contains_path_part(path, ("generated",)) for path in lowered):
        add("generated_files")

    if any(path.endswith("/__init__.py") for path in lowered):
        add("public_api_changes")

    if any(path.rsplit("/", 1)[-1] in _DEPENDENCY_FILES for path in lowered):
        add("dependency_changes")

    source_paths = [path for path in lowered if path.startswith("src/")]
    test_paths = [path for path in lowered if path.startswith("tests/") or "/test_" in path]
    generated_source = any(_contains_path_part(path, ("generated",)) for path in source_paths)
    if source_paths and not test_paths and not generated_source:
        add("source_without_tests")

    irreversible_diff = any(token in diff_text for token in ("rm -rf", "terraform destroy"))
    if any(path.startswith("infra/terraform/") for path in lowered) or irreversible_diff:
        add("irreversible_infra")

    return categories, rule_categories


def _merged_rules(rule_set: RuleSet | None) -> dict[Category, dict[str, object]]:
    merged: dict[Category, dict[str, object]] = {
        category: dict(values) for category, values in DEFAULT_RULE_SET.items()
    }
    if rule_set:
        overrides = cast(  # rule_set is RuleSet = dict[str, RuleOverride] | None; None excluded by enclosing if
            "dict[str, RuleOverride]", rule_set
        )
        for raw_category, override in overrides.items():
            if raw_category not in DEFAULT_RULE_SET:
                continue
            category = raw_category
            current = merged[category]
            current.update(override)
    return merged


def _is_small_isolated_source(paths: list[str], diff_stats: dict[str, object]) -> bool:
    if len(paths) != 1 or not paths[0].lower().startswith("src/"):
        return False
    added = diff_stats.get("lines_added")
    deleted = diff_stats.get("lines_deleted")
    return isinstance(added, int) and isinstance(deleted, int) and added + deleted <= 5


def classify_blast_radius(
    change: ChangeSet, *, rule_set: RuleSet | None = None
) -> BlastRadiusClassification:
    """Classify typed change data without filesystem, network, or environment access."""
    paths = change.get("changed_paths", [])
    diff_stats = change.get("diff_stats", {})
    categories, rule_categories = _detected_categories(paths, _diff_text(diff_stats))
    rules = _merged_rules(rule_set)

    lanes: list[Lane] = [
        cast(  # rules values are Lane literals set by DEFAULT_RULE_SET; dict access returns object
            "Lane", rules[category]["lane"]
        )
        for category in rule_categories
        if "lane" in rules[category]
    ]
    lane: Lane = "low"
    for candidate in lanes:
        if _LANE_RANK[candidate] > _LANE_RANK[lane]:
            lane = candidate
    has_source = any(path.lower().startswith("src/") for path in paths)
    if lane == "low" and has_source and "generated_files" not in rule_categories:
        lane = "medium"

    source_override = rule_set is not None and "source_without_tests" in rule_set
    if lane == "medium" and _is_small_isolated_source(paths, diff_stats) and not source_override:
        lane = "low"

    if "generated_files" in rule_categories and lane == "high":
        lane = "high"

    reason = (
        f"Detected blast-radius categories: {', '.join(categories)}."
        if categories
        else "No elevated blast-radius category was detected."
    )
    return BlastRadiusClassification(
        lane=lane,
        auto_merge_lane=_AUTO_MERGE_LANE[lane],
        reason=reason,
        next_action=_NEXT_ACTION[lane],
        categories=categories,
    )


__all__ = [
    "DEFAULT_RULE_SET",
    "AutoMergeLane",
    "BlastRadiusClassification",
    "ChangeSet",
    "Lane",
    "RuleSet",
    "classify_blast_radius",
]
