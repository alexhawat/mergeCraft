"""Pure blast-radius classification for merge evidence (#48)."""

from __future__ import annotations

import re
from typing import Final, Literal, NamedTuple, NotRequired, cast

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from mergecraft.classify.path_globs import path_full_matches_glob
from mergecraft.classify.review_config import is_review_config_path
from mergecraft.review_policy.manifest_names import (
    BUILD_MANIFEST_NAMES,
    is_dependency_manifest_path,
)

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
    "review_config",
]


class ScopeSignal(TypedDict):
    """The declared ``Scope paths:`` of a change, as the classifier reads it (#1056 part 3).

    ``declared`` is ``False`` when no source carried a block (the scope is
    unknown); ``invalid`` is ``True`` when the block broke a bound; ``globs`` are
    the accepted globs, matched against the changed paths only.
    """

    declared: bool
    globs: list[str]
    invalid: bool


FixProofStatus = Literal[
    "proven",
    "not-proven",
    "no-tests",
    "no-receipt",
    "invalid",
    "mismatch",
    "not-declared",
    "not-required",
]


class FixProofSignal(TypedDict):
    """Whether a change needs fail-then-pass proof, and what its receipt showed (#1056 part 5).

    ``required`` is ``True`` for a fix pull request (conventional ``fix`` type or a
    ``review.fixLabels`` label); ``status`` is the recorded receipt status
    (``mergecraft.ci.red_green``), or ``not-required`` for a change that is not a fix.
    ``detail`` is the recorded evidence's own sentence (why there is no receipt, which
    fork ran it, what the size was); the unproven reasons repeat it.
    """

    required: bool
    status: FixProofStatus
    detail: NotRequired[str]


class ChangeSet(TypedDict, total=False):
    """Side-effect-free change payload fed to the classifier.

    ``scope`` and ``fix_proof`` are optional: without one, its gate is left out of
    the checklist (a library caller); a review run always supplies both.
    """

    changed_paths: list[str]
    diff_stats: dict[str, object]
    scope: ScopeSignal
    fix_proof: FixProofSignal


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
    review_config: RuleOverride


class LaneReason(BaseModel):
    """One coded reason behind a lane (#1056).

    ``code`` is a key of :data:`LANE_REASON_CATALOGUE`. ``lane`` is the lane this
    reason forces **after** repository overrides and the small isolated-source
    carve-out, so it can differ from the catalogue default; ``message`` says why
    when it does.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    lane: Lane
    message: str


class ChecklistGate(BaseModel):
    """One checklist gate: ``True`` passed, ``False`` failed, ``None`` not measured."""

    model_config = ConfigDict(extra="forbid")

    gate: str
    passed: bool | None


class BlastRadiusClassification(BaseModel):
    """Deterministic lane decision and the signals that produced it.

    ``reasons`` and ``checklist`` default to empty so a packet written before
    they existed (schema ``1.17.0``) still validates; :func:`classify_blast_radius`
    always emits at least one reason and every gate in :data:`GATE_ORDER`.
    """

    model_config = ConfigDict(extra="forbid")

    lane: Lane
    auto_merge_lane: AutoMergeLane
    reason: str
    next_action: str
    categories: list[str]
    reasons: list[LaneReason] = Field(default_factory=list)
    checklist: list[ChecklistGate] = Field(default_factory=list)


DEFAULT_RULE_SET: dict[Category, RuleOverride] = {
    "migrations": {"lane": "high"},
    "auth_security_payment": {"lane": "high"},
    "secrets_config_deployment": {"lane": "high"},
    "generated_files": {"lane": "low"},
    "public_api_changes": {"lane": "medium"},
    "dependency_changes": {"lane": "medium"},
    "source_without_tests": {"lane": "medium"},
    "irreversible_infra": {"lane": "high"},
    # Config that governs how the PR is reviewed (#942): never auto-merge eligible.
    "review_config": {"lane": "medium"},
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
# Paths that are not hand-written source: documentation, tests, binary assets.
_DOC_SUFFIXES: Final[tuple[str, ...]] = (
    ".md",
    ".mdx",
    ".markdown",
    ".rst",
    ".adoc",
    ".txt",
)
_DOC_NAMES: Final[frozenset[str]] = frozenset(
    {"license", "licence", "notice", "authors", "contributors", "copying", "codeowners"}
)
_DOC_DIRS: Final[tuple[str, ...]] = ("docs", "doc")
_ASSET_SUFFIXES: Final[tuple[str, ...]] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".pdf",
)
# Declarative config is not code that needs a test; the deployment, secrets and
# review-config reasons judge the config paths that matter.
_CONFIG_SUFFIXES: Final[tuple[str, ...]] = (
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".conf",
    ".lock",
    ".jsonl",
    ".csv",
    ".tsv",
    ".xml",
)
_TEST_DIRS: Final[frozenset[str]] = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_TEST_NAME: Final[re.Pattern[str]] = re.compile(
    r"^test_|_test\.[a-z0-9]+$|\.(?:test|spec)\.[a-z0-9]+$|_spec\.[a-z0-9]+$"
)
_DEPLOYMENT_DIRS: Final[tuple[str, ...]] = (
    "deploy",
    "k8s",
    "kubernetes",
    "helm",
    "charts",
    "overlays",
)
_DEPLOYMENT_NAMES: Final[frozenset[str]] = frozenset(
    {"chart.yaml", "kustomization.yaml", "kustomization.yml"}
)
_DESTRUCTIVE_SQL: Final[re.Pattern[str]] = re.compile(r"\b(?:drop|alter|create)\s+table\b")
_IRREVERSIBLE_COMMAND: Final[re.Pattern[str]] = re.compile(
    r"\brm\s+(?:-[a-z]*r[a-z]*f[a-z]*|-[a-z]*f[a-z]*r[a-z]*"
    r"|(?:--recursive\s+--force|--force\s+--recursive)|-r\s+-f|-f\s+-r)\b"
    r"|\bterraform\s+destroy\b"
)
_SECRET_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"(?:password|secret_key|private_key)\s*=|aws_secret_access_key"
)
_DIFF_SIGNAL_KEYS = ("diff", "diff_text", "patch", "text")

SIGNAL_MISSING_CATEGORY = "signal_missing"
"""Category recorded when the classifier was not given the inputs it measures.

Unknown is never green (#1056): a classification with no changed paths or no
diff statistics cannot vouch for a ``low`` lane, so it carries a
``signal.missing.*`` reason at ``medium`` (``assisted``, never ``eligible``). It
is not a :data:`Category` rule key on purpose, so no repository override can
lower it.
"""


def _contains_path_part(path: str, parts: tuple[str, ...]) -> bool:
    normalized = f"/{path.lower().strip('/')}"
    return any(f"/{part}/" in f"{normalized}/" for part in parts)


def _is_generated(path: str) -> bool:
    return _contains_path_part(path, ("generated",))


def _is_test_path(path: str) -> bool:
    """A path under a test directory, or a file named like a test in any language."""
    segments = path.lower().strip("/").split("/")
    return bool(_TEST_DIRS & set(segments[:-1])) or _TEST_NAME.search(segments[-1]) is not None


def _is_doc_path(path: str) -> bool:
    lowered = path.lower().strip("/")
    if is_dependency_manifest_path(lowered) or lowered.rsplit("/", 1)[-1] in {
        name.lower() for name in BUILD_MANIFEST_NAMES
    }:
        return False
    if lowered.rsplit("/", 1)[-1] in _DOC_NAMES:
        return True
    return lowered.endswith(_DOC_SUFFIXES) or _contains_path_part(lowered, _DOC_DIRS)


def _is_hand_written_source(path: str) -> bool:
    """Any path that is not documentation, a test, an asset, config, generated output or a manifest.

    Repositories keep code in ``app/``, ``lib/``, ``cmd/``, ``scripts/`` or the root,
    not only ``src/``, so source is what is left once the known non-source kinds are
    removed. Dependency manifests and lockfiles have their own ``deps.changed`` reason;
    declarative config (``.toml``, ``.yaml``, ``.json`` and dotfiles) is judged by the
    deployment, secrets and review-config reasons instead.
    """
    lowered = path.lower().strip("/")
    return not (
        _is_doc_path(lowered)
        or _is_test_path(lowered)
        or _is_generated(lowered)
        or lowered.endswith((*_ASSET_SUFFIXES, *_CONFIG_SUFFIXES))
        or lowered.rsplit("/", 1)[-1].startswith(".")
        or is_dependency_manifest_path(lowered)
    )


def _has_hand_written_source(paths: list[str]) -> bool:
    """Whether any changed path is hand-written source (see :func:`_is_hand_written_source`)."""
    return any(_is_hand_written_source(path) for path in paths)


def _is_deployment_path(path: str) -> bool:
    """A Dockerfile, a composite action, a Helm chart or Kustomize file, or a deploy tree.

    Documentation and test fixtures under such a directory are not deployment.
    """
    if _is_doc_path(path) or _is_test_path(path):
        return False
    name = path.rsplit("/", 1)[-1]
    if name in _DEPLOYMENT_NAMES:
        return True
    if name.startswith("dockerfile") or name.endswith(".dockerfile"):
        return True
    if path.startswith(".github/actions/"):
        return True
    return _contains_path_part(path, _DEPLOYMENT_DIRS)


def _diff_text(diff_stats: dict[str, object]) -> str:
    return "\n".join(
        value for key in _DIFF_SIGNAL_KEYS if isinstance((value := diff_stats.get(key)), str)
    ).lower()


LANE_REASON_CATALOGUE: dict[str, Lane] = {
    "signal.missing.paths": "medium",
    "signal.missing.diff": "medium",
    "paths.migrations": "high",
    "paths.auth": "high",
    "paths.security": "high",
    "paths.payment": "high",
    "paths.permissions": "high",
    "paths.secrets_config": "high",
    "paths.deployment": "high",
    "paths.irreversible_infra": "high",
    "diff.destructive_sql": "high",
    "diff.secret_assignment": "high",
    "diff.irreversible_command": "high",
    "paths.public_api": "medium",
    "deps.changed": "medium",
    "tests.missing": "medium",
    "paths.review_config": "medium",
    "source.changed": "medium",
    "paths.generated": "low",
    "source.small_isolated": "low",
    "baseline.clean": "low",
    "scope.unknown": "medium",
    "scope.undeclared": "medium",
    "scope.invalid": "medium",
    "scope.drift": "medium",
    "scope.within": "low",
    "fix.not-required": "low",
    "fix.proven": "low",
    "fix.not-proven": "medium",
    "fix.no-receipt": "medium",
    "fix.receipt.invalid": "medium",
    "fix.receipt.mismatch": "medium",
}
"""The closed catalogue of lane-reason codes and their **default** lanes (#1056).

An emitted :class:`LaneReason` carries the lane it forces after repository
overrides and the small isolated-source carve-out; the default here never
changes. ``docs/blast-radius.md`` lists every code (the *Lane reasons* table).
"""

GATE_ORDER: tuple[str, ...] = (
    "inputs",
    "migrations",
    "auth_security_payment",
    "secrets_config_deployment",
    "irreversible_infra",
    "public_api",
    "dependencies",
    "tests",
    "review_config",
    "source",
    "scope",
    "fix_proof",
)
"""The fixed order of :attr:`BlastRadiusClassification.checklist` gates.

``scope`` and ``fix_proof`` are listed only when the change set carries the
matching signal; every other gate is always listed.
"""

_OPTIONAL_GATES: frozenset[str] = frozenset({"scope", "fix_proof"})

_Input = Literal["paths", "diff"]

# What each gate reads. A gate whose inputs were not all given is ``None`` (not
# measured) unless a reason already failed it: unknown is never green, and a
# measured failure is never hidden behind ``None``. ``inputs`` is special-cased.
_GATE_INPUTS: dict[str, tuple[_Input, ...]] = {
    "migrations": ("paths", "diff"),
    "auth_security_payment": ("paths",),
    "secrets_config_deployment": ("paths", "diff"),
    "irreversible_infra": ("paths", "diff"),
    "public_api": ("paths",),
    "dependencies": ("paths",),
    "tests": ("paths", "diff"),
    "review_config": ("paths",),
    "source": ("paths", "diff"),
}


class _ReasonSpec(NamedTuple):
    """Which ``RuleSet`` key may override a code, and which gate it fails above ``low``."""

    rule: Category | None
    gate: str | None


_REASON_SPECS: dict[str, _ReasonSpec] = {
    "signal.missing.paths": _ReasonSpec(None, "inputs"),
    "signal.missing.diff": _ReasonSpec(None, "inputs"),
    "paths.migrations": _ReasonSpec("migrations", "migrations"),
    "diff.destructive_sql": _ReasonSpec("migrations", "migrations"),
    "paths.auth": _ReasonSpec("auth_security_payment", "auth_security_payment"),
    "paths.security": _ReasonSpec("auth_security_payment", "auth_security_payment"),
    "paths.payment": _ReasonSpec("auth_security_payment", "auth_security_payment"),
    "paths.permissions": _ReasonSpec("auth_security_payment", "auth_security_payment"),
    "paths.secrets_config": _ReasonSpec("secrets_config_deployment", "secrets_config_deployment"),
    "paths.deployment": _ReasonSpec("secrets_config_deployment", "secrets_config_deployment"),
    "diff.secret_assignment": _ReasonSpec("secrets_config_deployment", "secrets_config_deployment"),
    "paths.irreversible_infra": _ReasonSpec("irreversible_infra", "irreversible_infra"),
    "diff.irreversible_command": _ReasonSpec("irreversible_infra", "irreversible_infra"),
    "paths.public_api": _ReasonSpec("public_api_changes", "public_api"),
    "deps.changed": _ReasonSpec("dependency_changes", "dependencies"),
    "tests.missing": _ReasonSpec("source_without_tests", "tests"),
    "paths.review_config": _ReasonSpec("review_config", "review_config"),
    "source.changed": _ReasonSpec(None, "source"),
    # Generated output is ``low`` by default; an override that raises it fails ``source``.
    "paths.generated": _ReasonSpec("generated_files", "source"),
    "source.small_isolated": _ReasonSpec(None, None),
    "baseline.clean": _ReasonSpec(None, None),
    # ``scope.unknown`` leaves the gate ``None`` (not measured) rather than failing it.
    "scope.unknown": _ReasonSpec(None, None),
    "scope.undeclared": _ReasonSpec(None, "scope"),
    "scope.invalid": _ReasonSpec(None, "scope"),
    "scope.drift": _ReasonSpec(None, "scope"),
    "scope.within": _ReasonSpec(None, None),
    "fix.not-required": _ReasonSpec(None, None),
    "fix.proven": _ReasonSpec(None, None),
    "fix.not-proven": _ReasonSpec(None, "fix_proof"),
    "fix.no-receipt": _ReasonSpec(None, "fix_proof"),
    "fix.receipt.invalid": _ReasonSpec(None, "fix_proof"),
    "fix.receipt.mismatch": _ReasonSpec(None, "fix_proof"),
}

# Floors a repository override may raise but never lower: the review-config
# floor (#942) — a PR that edits its own review config is never ``eligible``.
# ``signal.*`` has no ``RuleSet`` key at all, so nothing can override it.
_OVERRIDE_FLOORS: frozenset[str] = frozenset({"paths.review_config"})

_SMALL_SOURCE_MAX_LINES = 5
_SCOPE_DRIFT_MAX_LISTED = 10


def _detect(paths: list[str], diff_text: str) -> tuple[list[str], dict[str, str]]:
    """Return the legacy category labels and the detected codes with their messages."""
    categories: list[str] = []
    hits: dict[str, str] = {}

    def add(code: str, message: str, *labels: str) -> None:
        hits.setdefault(code, message)
        for label in labels:
            if label not in categories:
                categories.append(label)

    lowered = [path.lower().strip("/") for path in paths]
    if any(_contains_path_part(path, ("migration", "migrations")) for path in lowered):
        add("paths.migrations", "a changed path is under a migrations directory", "migrations")
    if _DESTRUCTIVE_SQL.search(diff_text):
        add(
            "diff.destructive_sql",
            "the diff text contains a schema-changing SQL statement",
            "migrations",
        )

    for path in lowered:
        if _contains_path_part(path, ("auth",)):
            add(
                "paths.auth",
                "a changed path is under an auth directory",
                "auth_security_payment",
                "auth",
            )
        if _contains_path_part(path, ("security",)):
            add(
                "paths.security",
                "a changed path is under a security directory",
                "auth_security_payment",
                "security",
            )
        if _contains_path_part(path, ("payment", "payments", "billing")):
            add(
                "paths.payment",
                "a changed path is under a payment or billing directory",
                "auth_security_payment",
                "payment",
            )
        if _contains_path_part(path, ("permission", "permissions")):
            add(
                "paths.permissions",
                "a changed path is under a permissions directory",
                "auth_security_payment",
                "permissions",
            )

    secret_diff = _SECRET_ASSIGNMENT.search(diff_text) is not None
    workflow_path = any(path.startswith(".github/workflows/") for path in lowered)
    deployment_path = any(_is_deployment_path(path) for path in lowered)
    secrets_config_path = any(
        path.startswith("config/") or path == ".env.example" for path in lowered
    )
    if secret_diff or workflow_path or deployment_path or secrets_config_path:
        labels = ["secrets_config_deployment"]
        if workflow_path or deployment_path:
            labels.append("deployment")
        if secrets_config_path:
            labels.append("secrets_config")
        if workflow_path:
            add("paths.deployment", "a GitHub Actions workflow changed", *labels)
        if deployment_path:
            add(
                "paths.deployment",
                "a Dockerfile, composite action, or deploy / Kubernetes / Helm path changed",
                *labels,
            )
        if secrets_config_path:
            add(
                "paths.secrets_config",
                "a path under config/ or .env.example changed",
                *labels,
            )
        if secret_diff:
            add(
                "diff.secret_assignment",
                "the diff text contains a secret-assignment marker",
                *labels,
            )

    if any(_is_generated(path) for path in lowered):
        add("paths.generated", "a changed path is generated output", "generated_files")

    if any(path.endswith("/__init__.py") for path in lowered):
        add("paths.public_api", "a package __init__.py changed", "public_api_changes")

    if any(is_dependency_manifest_path(path) for path in lowered):
        add("deps.changed", "a dependency manifest or lockfile changed", "dependency_changes")

    # A generated path exempts only itself: a hand-written source path beside it
    # still needs a test change.
    test_paths = [path for path in lowered if _is_test_path(path)]
    if _has_hand_written_source(lowered) and not test_paths:
        add(
            "tests.missing",
            "source changed without a test change",
            "source_without_tests",
        )

    if any(is_review_config_path(path) for path in paths):
        add(
            "paths.review_config",
            "config that governs how this pull request is reviewed changed",
            "review_config",
        )

    if any(path.startswith("infra/terraform/") for path in lowered):
        add(
            "paths.irreversible_infra",
            "a path under infra/terraform/ changed",
            "irreversible_infra",
        )
    if _IRREVERSIBLE_COMMAND.search(diff_text):
        add(
            "diff.irreversible_command",
            "the diff text contains an irreversible command",
            "irreversible_infra",
        )

    return categories, hits


def _override_lanes(rule_set: RuleSet | None) -> dict[Category, Lane]:
    """The valid per-category lane overrides a repository supplied (unknown keys ignored)."""
    if not rule_set:
        return {}
    overrides = cast(  # RuleSet is a TypedDict; iterate it as the plain mapping it is at runtime
        "dict[str, object]", rule_set
    )
    lanes: dict[Category, Lane] = {}
    for raw_category, override in overrides.items():
        if raw_category not in DEFAULT_RULE_SET or not isinstance(override, dict):
            continue
        lane = override.get("lane")
        if lane in _LANE_RANK:
            lanes[raw_category] = cast(  # membership in _LANE_RANK proves a Lane literal
                "Lane", lane
            )
    return lanes


def _is_small_isolated_source(paths: list[str], diff_stats: dict[str, object]) -> bool:
    if len(paths) != 1 or not _is_hand_written_source(paths[0]):
        return False
    added = diff_stats.get("lines_added")
    deleted = diff_stats.get("lines_deleted")
    return (
        isinstance(added, int)
        and isinstance(deleted, int)
        and added + deleted <= _SMALL_SOURCE_MAX_LINES
    )


def _missing_signals(change: ChangeSet) -> list[str]:
    """Name each classifier input that is absent or empty (#1056)."""
    missing: list[str] = []
    paths = change.get("changed_paths")
    if not isinstance(paths, list) or not paths:
        missing.append("changed_paths")
    diff_stats = change.get("diff_stats")
    if not isinstance(diff_stats, dict):
        missing.append("diff_stats")
    return missing


def _max_lane(lanes: list[Lane]) -> Lane:
    lane: Lane = "low"
    for candidate in lanes:
        if _LANE_RANK[candidate] > _LANE_RANK[lane]:
            lane = candidate
    return lane


def _apply_override(code: str, message: str, overrides: dict[Category, Lane]) -> LaneReason:
    """The reason for ``code`` at its catalogue default, or at the repository override."""
    default = LANE_REASON_CATALOGUE[code]
    rule = _REASON_SPECS[code].rule
    override = overrides.get(rule) if rule is not None else None
    if override is None or override == default:
        return LaneReason(code=code, lane=default, message=message)
    if code in _OVERRIDE_FLOORS and _LANE_RANK[override] < _LANE_RANK[default]:
        return LaneReason(
            code=code,
            lane=default,
            message=(
                f"{message}; the repository override to {override} is ignored: "
                f"this reason is never below {default}"
            ),
        )
    return LaneReason(
        code=code,
        lane=override,
        message=f"{message} (lane {default} → {override} by repository override)",
    )


def _lane_reasons(
    *,
    missing: list[str],
    hits: dict[str, str],
    paths: list[str],
    diff_stats: dict[str, object],
    rule_set: RuleSet | None,
) -> list[LaneReason]:
    """Every coded reason, each at the lane it forces after overrides and the carve-out."""
    overrides = _override_lanes(rule_set)
    reasons: list[LaneReason] = []
    if "changed_paths" in missing:
        reasons.append(
            LaneReason(
                code="signal.missing.paths",
                lane=LANE_REASON_CATALOGUE["signal.missing.paths"],
                message="no changed paths were given, so no path gate was measured",
            )
        )
    if "diff_stats" in missing:
        reasons.append(
            LaneReason(
                code="signal.missing.diff",
                lane=LANE_REASON_CATALOGUE["signal.missing.diff"],
                message=(
                    "no diff statistics were given, so the diff-text and line-count "
                    "checks were not measured"
                ),
            )
        )
    measured = [_apply_override(code, message, overrides) for code, message in hits.items()]

    rule_categories = {spec.rule for code in hits if (spec := _REASON_SPECS[code]).rule}
    # A generated path exempts only itself; any hand-written path is a source change.
    if _has_hand_written_source(paths):
        measured.append(
            LaneReason(
                code="source.changed",
                lane=LANE_REASON_CATALOGUE["source.changed"],
                message="hand-written source changed",
            )
        )

    # The carve-out exists for a tiny isolated source edit — not for a tiny edit
    # to the config that governs how this PR is reviewed (#942), not when the
    # repository overrides ``source_without_tests``, and not beside a ``high``
    # reason. It lowers only the source and tests reasons, and says so.
    carvable = {"source.changed", "tests.missing"}
    others_high = any(r.lane == "high" for r in measured if r.code not in carvable)
    if (
        any(r.code in carvable for r in measured)
        and not others_high
        and "review_config" not in rule_categories
        and not (rule_set is not None and "source_without_tests" in rule_set)
        and _is_small_isolated_source(paths, diff_stats)
    ):
        carved: list[LaneReason] = []
        for reason in measured:
            if reason.code == "tests.missing":
                carved.append(
                    LaneReason(
                        code="tests.missing",
                        lane="low",
                        message=(
                            f"{reason.message} (lane {reason.lane} → low by the small "
                            "isolated-source carve-out)"
                        ),
                    )
                )
            elif reason.code != "source.changed":
                carved.append(reason)
        carved.append(
            LaneReason(
                code="source.small_isolated",
                lane=LANE_REASON_CATALOGUE["source.small_isolated"],
                message=(
                    "one source file with at most "
                    f"{_SMALL_SOURCE_MAX_LINES} changed lines: the small isolated-source "
                    "carve-out applies"
                ),
            )
        )
        measured = carved

    reasons.extend(measured)
    if not reasons:
        reasons.append(
            LaneReason(
                code="baseline.clean",
                lane=LANE_REASON_CATALOGUE["baseline.clean"],
                message="no elevated blast-radius signal was detected",
            )
        )
    return reasons


def _scope_reason(code: str, message: str) -> LaneReason:
    return LaneReason(code=code, lane=LANE_REASON_CATALOGUE[code], message=message)


def _scope_outcome(change: ChangeSet, paths: list[str]) -> tuple[list[LaneReason], bool | None]:
    """The ``scope.*`` reasons and the ``scope`` gate for a supplied signal.

    Glob text is untrusted and never appears in a message; only changed paths do.
    A malformed signal reads as not declared, so it can never pass the gate.
    """
    raw = change.get("scope")
    signal: dict[str, object] = (
        cast("dict[str, object]", raw)  # reason: the TypedDict is a plain dict at runtime
        if isinstance(raw, dict)
        else {}
    )
    if signal.get("declared") is not True:
        return [
            _scope_reason(
                "scope.unknown",
                "no Scope paths: block was found in the pull request or the issues it "
                "closes, so the changed paths were not checked against a declared scope",
            )
        ], None
    if signal.get("invalid") is True:
        return [
            _scope_reason(
                "scope.invalid",
                "the Scope paths: block broke a bound, so it declares nothing",
            )
        ], False
    raw_globs = signal.get("globs")
    globs = (
        [glob for glob in raw_globs if isinstance(glob, str) and glob]
        if isinstance(raw_globs, list)
        else []
    )
    if not globs:
        return [_scope_reason("scope.undeclared", "the Scope paths: block lists no globs")], False
    if not paths:
        # No changed paths to check: not measured (``signal.missing.paths`` says why).
        return [], None
    outside = [path for path in paths if not any(path_full_matches_glob(g, path) for g in globs)]
    if not outside:
        return [
            _scope_reason(
                "scope.within",
                f"every changed path ({len(paths)}) is inside the declared scope",
            )
        ], True
    listed = ", ".join(outside[:_SCOPE_DRIFT_MAX_LISTED])
    more = len(outside) - _SCOPE_DRIFT_MAX_LISTED
    suffix = f" (and {more} more)" if more > 0 else ""
    return [
        _scope_reason(
            "scope.drift",
            f"{len(outside)} changed path(s) outside the declared scope: {listed}{suffix}",
        )
    ], False


# A fix pull request's receipt status → the reason code and its message (#1056 part 5).
_FIX_PROOF_OUTCOMES: dict[str, tuple[str, str]] = {
    "proven": (
        "fix.proven",
        "a fail-then-pass receipt for this pull request's exact base and head SHAs shows a "
        "test failing on the base and every listed test passing on the head",
    ),
    "not-proven": (
        "fix.not-proven",
        "the fail-then-pass receipt does not prove the fix: no listed test failed on the "
        "base, or a listed test did not pass on the head",
    ),
    "no-tests": (
        "fix.not-proven",
        "the fail-then-pass receipt lists no tests, so it proves nothing",
    ),
    "no-receipt": (
        "fix.no-receipt",
        "this is a fix pull request and no successful workflow run on the head SHA "
        "provided a readable fail-then-pass receipt",
    ),
    "not-declared": (
        "fix.no-receipt",
        "this is a fix pull request and the repository declares no "
        "ciEvidence.redGreen receipt on its base, so the fix cannot be proven",
    ),
    "invalid": (
        "fix.receipt.invalid",
        "the fail-then-pass receipt could not be read: malformed, the wrong schema, or "
        "over the size cap",
    ),
    "mismatch": (
        "fix.receipt.mismatch",
        "the fail-then-pass receipt was produced for other commits: its base and head SHAs "
        "do not match this pull request's",
    ),
}


# The unproven reasons whose message repeats the evidence detail.
_FIX_PROOF_DETAILED: frozenset[str] = frozenset(
    {"fix.no-receipt", "fix.receipt.invalid", "fix.receipt.mismatch"}
)


def _fix_proof_outcome(change: ChangeSet) -> tuple[list[LaneReason], bool]:
    """The one ``fix.*`` reason and the ``fix_proof`` gate for a supplied signal.

    Only ``required is False`` reads as "not a fix"; any other value, and any
    status outside the vocabulary, fails closed as a missing receipt.
    """
    raw = change.get("fix_proof")
    signal: dict[str, object] = (
        cast("dict[str, object]", raw)  # reason: the TypedDict is a plain dict at runtime
        if isinstance(raw, dict)
        else {}
    )
    if signal.get("required") is False:
        code = "fix.not-required"
        message = (
            "not a fix pull request (no conventional fix type and no fix label), so no "
            "fail-then-pass receipt is required"
        )
    else:
        status = signal.get("status")
        code, message = _FIX_PROOF_OUTCOMES.get(
            status if isinstance(status, str) else "",
            (
                "fix.no-receipt",
                "this is a fix pull request and its fail-then-pass receipt status is unknown",
            ),
        )
        detail = signal.get("detail")
        if code in _FIX_PROOF_DETAILED and isinstance(detail, str) and detail.strip():
            message = f"{message} ({detail.strip()})"
    reason = LaneReason(code=code, lane=LANE_REASON_CATALOGUE[code], message=message)
    return [reason], code in {"fix.not-required", "fix.proven"}


def _checklist(
    reasons: list[LaneReason],
    missing: list[str],
    *,
    optional: dict[str, bool | None],
) -> list[ChecklistGate]:
    """Every gate in :data:`GATE_ORDER`: ``False`` when a reason forces it above ``low``,
    ``True`` when measured and clean, ``None`` when its inputs were not given.

    An optional gate (``scope``, ``fix_proof``) is listed only when ``optional``
    names it, with the value its own signal produced."""
    failed = {
        gate
        for reason in reasons
        if reason.lane != "low" and (gate := _REASON_SPECS[reason.code].gate) is not None
    }
    given: set[_Input] = set()
    if "changed_paths" not in missing:
        given.add("paths")
    if "diff_stats" not in missing:
        given.add("diff")
    gates: list[ChecklistGate] = []
    for gate in GATE_ORDER:
        passed: bool | None
        if gate in _OPTIONAL_GATES:
            if gate not in optional:
                continue
            passed = optional[gate]
        elif gate == "inputs":
            passed = not missing
        elif gate in failed:
            passed = False
        elif set(_GATE_INPUTS[gate]) <= given:
            passed = True
        else:
            passed = None
        gates.append(ChecklistGate(gate=gate, passed=passed))
    return gates


def classify_blast_radius(
    change: ChangeSet, *, rule_set: RuleSet | None = None
) -> BlastRadiusClassification:
    """Classify typed change data without filesystem, network, or environment access.

    The lane is the highest lane over the coded ``reasons``; ``auto_merge_lane``
    is ``eligible`` exactly when every ``checklist`` gate passed, which is exactly
    when the lane is ``low``. Missing or empty ``changed_paths``, or missing
    ``diff_stats``, add the :data:`SIGNAL_MISSING_CATEGORY` category, a
    ``signal.missing.*`` reason at ``medium`` that no override can lower, and
    ``None`` (not measured) for every gate that reads the missing input.

    A ``scope`` signal adds the ``scope`` gate and one ``scope.*`` reason: every
    changed path inside a declared glob is ``scope.within`` (gate ``True``); any
    path outside is ``scope.drift``; a block with no globs is ``scope.undeclared``;
    a block that broke a bound is ``scope.invalid`` (gate ``False``, all
    ``medium``); no declaration is ``scope.unknown`` (``medium``, gate ``None``).
    Without a ``scope`` key the gate is left out and nothing else changes.
    A ``fix_proof`` signal adds the ``fix_proof`` gate and one ``fix.*`` reason: a
    change that is not a fix is ``fix.not-required`` and a fix with a ``proven``
    receipt is ``fix.proven`` (both ``low``, gate ``True``); every other receipt
    status is ``medium`` with its own code and gate ``False``. Without a
    ``fix_proof`` key the gate is left out and nothing else changes.
    """
    missing = _missing_signals(change)
    raw_paths = change.get("changed_paths")
    paths = raw_paths if isinstance(raw_paths, list) else []
    raw_stats = change.get("diff_stats")
    diff_stats = raw_stats if isinstance(raw_stats, dict) else {}
    categories, hits = _detect(paths, _diff_text(diff_stats))
    reasons = _lane_reasons(
        missing=missing, hits=hits, paths=paths, diff_stats=diff_stats, rule_set=rule_set
    )
    optional: dict[str, bool | None] = {}
    if "scope" in change:
        scope_reasons, optional["scope"] = _scope_outcome(change, paths)
        reasons.extend(scope_reasons)
    if "fix_proof" in change:
        fix_reasons, optional["fix_proof"] = _fix_proof_outcome(change)
        reasons.extend(fix_reasons)
    lane = _max_lane([reason.lane for reason in reasons])
    if missing:
        categories.append(SIGNAL_MISSING_CATEGORY)

    sentence = (
        f"Detected blast-radius categories: {', '.join(categories)}."
        if categories
        else "No elevated blast-radius category was detected."
    )
    if missing:
        sentence = f"{sentence} Missing classifier input: {', '.join(missing)}."
    codes = ", ".join(reason.code for reason in reasons)
    return BlastRadiusClassification(
        lane=lane,
        auto_merge_lane=_AUTO_MERGE_LANE[lane],
        reason=f"Lane reasons: {codes}. {sentence}",
        next_action=_NEXT_ACTION[lane],
        categories=categories,
        reasons=reasons,
        checklist=_checklist(reasons, missing, optional=optional),
    )


__all__ = [
    "DEFAULT_RULE_SET",
    "GATE_ORDER",
    "LANE_REASON_CATALOGUE",
    "SIGNAL_MISSING_CATEGORY",
    "AutoMergeLane",
    "BlastRadiusClassification",
    "ChangeSet",
    "ChecklistGate",
    "FixProofSignal",
    "FixProofStatus",
    "Lane",
    "LaneReason",
    "RuleSet",
    "ScopeSignal",
    "classify_blast_radius",
]
