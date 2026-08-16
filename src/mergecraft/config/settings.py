"""Local repo settings, learnings TOC, and run-context assembly (no mergecraft.com API)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from mergecraft.classify import RuleSet
from mergecraft.types import PushPermission, ShellPermission  # noqa: TC001

AccountPlan = Literal["none", "payg"]
HeadingDepth = Literal[1, 2, 3, 4, 5, 6]

# D4 / D8 / W6.2 — security/runtime and optional-feature models both use
# ``extra="forbid"``. The optional-feature one-release warning shim has ended
# (D8 flipped at pre-0.0.1; see ``docs/config-failure-policy.md``).
_SECURITY_RUNTIME_EXTRA: Literal["forbid"] = "forbid"
_OPTIONAL_FEATURE_EXTRA: Literal["forbid"] = "forbid"


def _warn_unknown_config_keys(model_name: str, data: object, fields: dict[str, Any]) -> object:
    """Warn on unknown keys for optional-feature models (D4 one-release shim).

    The shim was retired in D8 (``_OPTIONAL_FEATURE_EXTRA = "forbid"``); the
    helper is preserved as a direct symbol anchor for tests that still assert
    it warns when called, and as a fallback for any future caller that wants
    to surface a soft warning before raising.
    """
    if not isinstance(data, dict):
        return data
    known: set[str] = set()
    for name, info in fields.items():
        known.add(name)
        alias = getattr(info, "alias", None)
        if isinstance(alias, str):
            known.add(alias)
    for key in data:
        if key not in known:
            logger.warning(
                "unknown config key {!r} on {} ignored "
                "(will be forbidden in a future release; see docs/config-failure-policy.md)",
                key,
                model_name,
            )
    return data


class _OptionalFeatureModel(BaseModel):
    """Optional-feature config models: ``extra="forbid"`` (D8)."""

    model_config = ConfigDict(extra=_OPTIONAL_FEATURE_EXTRA, populate_by_name=True)


class ModeDefinition(_OptionalFeatureModel):
    """Custom / built-in mode selectable via ``select_mode``."""

    id: str
    name: str
    description: str
    prompt: str = ""


class LearningsHeading(_OptionalFeatureModel):
    """TOC entry for a learnings markdown body (1-indexed line ranges)."""

    depth: HeadingDepth
    title: str
    start_line: int = Field(alias="startLine")
    end_line: int = Field(alias="endLine")


class StaticCheckDefinition(_OptionalFeatureModel):
    """A mechanical gate the repo declares for reviewers to run.

    ``command`` may contain a ``{files}`` token, replaced with the diff's changed
    paths. ``suffixes`` restricts the gate to diffs that touch matching files.
    """

    name: str
    command: str
    suffixes: list[str] = Field(default_factory=list)


class CiEvidenceSettings(_OptionalFeatureModel):
    """Which of the repo's *own* CI results mergeCraft may treat as evidence (#36).

    Both fields default empty, so a repo that declares no ``ciEvidence`` block
    sees identical behaviour and makes zero extra API calls (convention 9).

    ``gates`` maps a mergeCraft gate name — a ``staticChecks`` entry's ``name``,
    or a discovered Makefile target — to the exact GitHub check-run name that
    proves it. The mapping is explicit on purpose (D10): mergeCraft never infers
    that a check run *called* ``lint`` proves the ``lint`` gate, because a PR
    could add a workflow with any name it likes.

    ``sarifArtifacts`` lists workflow artifact names whose SARIF the reviewer may
    ingest as CI findings.
    """

    gates: dict[str, str] = Field(default_factory=dict)
    sarif_artifacts: list[str] = Field(default_factory=list, alias="sarifArtifacts")


class AnalyzerOverride(_OptionalFeatureModel):
    """Per-analyzer config override."""

    enabled: bool | None = None


# W10.1 — every gate this plan introduces defaults to ``shadow`` (D12).
# The two-mode vocabulary is closed: ``shadow`` records the prediction
# without enforcing; ``enforce`` applies the action as a gate. D12
# exists to prevent a brand-new gate from blocking on day one; the
# default mode is the single switch that prevents it.
GateMode = Literal["shadow", "enforce"]
"""Whether a gate this plan introduced runs in shadow (predict+record)
or enforce (apply the action as a gate). Every gate introduced by this
plan defaults to ``shadow`` (D12)."""


class GatesSettings(BaseModel):
    """Per-gate mode + override config (#46, #50, D12).

    The block is opt-in: a repo that does not declare one sees
    identical behaviour, and every gate runs in ``shadow`` by default.
    Enforcement is gated behind an explicit flip.

    The override is a rule-key -> action mapping that is layered on top
    of ``DEFAULT_GATE_POLICIES`` at the gate. The closed action
    vocabulary is enforced at the gate itself, so a mis-spelled value
    here is rejected by ``decide_action`` rather than silently widening
    the gate (W9.2).

    D4/W6.2 — ``extra="forbid"``: unknown keys are configuration errors.
    """

    model_config = ConfigDict(extra=_SECURITY_RUNTIME_EXTRA, populate_by_name=True)

    gate_action: GateMode = "shadow"
    thermostat: GateMode = "shadow"
    terminal_verdict: GateMode = "shadow"
    override: dict[str, str] = Field(default_factory=dict)


class AnalyzerPatternSettings(_OptionalFeatureModel):
    """Pattern backend selection for analyzer detection."""

    backend: str | None = None


class AnalyzersSettings(BaseModel):
    """Catalog analyzer configuration block.

    D4/W6.2 — ``extra="forbid"``: unknown keys are configuration errors.
    """

    model_config = ConfigDict(extra=_SECURITY_RUNTIME_EXTRA, populate_by_name=True)

    enabled: bool = True
    inline_budget: int = Field(default=8, alias="inlineBudget")
    base_comparison: str = Field(default="diff", alias="baseComparison")
    overrides: dict[str, AnalyzerOverride] = Field(default_factory=dict)
    pattern: AnalyzerPatternSettings = Field(default_factory=AnalyzerPatternSettings)
    # #39 / D13 — opt-in upload of analyzer findings to GitHub code scanning.
    # Off by default: a code-scanning alert is permanent and externally
    # visible, and the workflow also has to grant `security-events: write`
    # before the upload can succeed. The `sarif_upload` action input overrides
    # this in both directions when it is set (`resolve_sarif_upload_enabled`).
    sarif_upload: bool = Field(default=False, alias="sarifUpload")
    # #94 / S6 — change-impact extraction (impactPath), default off.
    # Produces a declaration-level reference-lead table for the diff at
    # review time. Off by default until the eval-bank corpus (#140) measures
    # its cost-to-benefit ratio (see S6 design at
    # .ignorelocal/waves/issues-setup-container-hygiene-wave-plan.md).
    impact: bool = Field(default=False, alias="impact")


# D5 / D9 / D15 — `tracing` block on `RepoSettings`. Additive-only, default off.
# The block is opt-in: a repo that does not declare one sees identical behaviour,
# identical performance, and zero egress (convention 9). See docs/TRACING.md.
# D15: no trust-related field; the doc states plainly that enabling a remote sink
# exports reviewed-repo content (W2.9 / W8.7).


class TraceSinkEntry(_OptionalFeatureModel):
    """One sink entry in ``tracing.sinks``.

    The ``_drop_unset`` serializer keeps the round-trip output identical to the
    YAML input: fields the operator never set are dropped from the dump (W1.1).
    Pydantic v2 only honours ``exclude_defaults`` from the outer
    ``model_dump(..., exclude_defaults=True)`` call, not from a nested model's
    ``model_config`` — so the filter is applied here at serialization time.

    The dump key may be an alias (when ``by_alias=True``) or the field name; the
    filter checks against ``__pydantic_fields_set__`` in both forms.
    """

    type: str
    path: str | None = None
    token_ref: str | None = Field(default=None, alias="tokenRef")
    project: str | None = None
    region: Literal["us", "eu"] = Field(default="us", alias="region")
    endpoint: str | None = None
    headers: dict[str, str] | None = None

    @model_serializer(mode="wrap")
    def _drop_unset(self, handler: Any) -> dict[str, Any]:
        """Drop fields that were not explicitly set on this model instance."""
        fields_set = self.__pydantic_fields_set__
        return {
            key: value
            for key, value in handler(self).items()
            if key in fields_set or _field_name_for(self, key) in fields_set
        }


_SHORTHAND_LOCAL_FILES_DEFAULT_PATH = ".mergecraft/traces/"


def _field_name_for(model: BaseModel, alias_or_name: str) -> str:
    """Map a serialized key (alias or field name) to the underlying field name.

    ``__pydantic_fields_set__`` tracks field names, but ``model_dump(by_alias=True)``
    emits aliases. This helper translates either back to the field name so the
    "drop unset fields" filter works in both cases.
    """
    fields = type(model).model_fields
    if alias_or_name in fields:
        return alias_or_name
    for name, info in fields.items():
        if info.alias == alias_or_name:
            return name
    return alias_or_name


class TracingSettings(BaseModel):
    """Tracing configuration block — sinks, retention, redaction.

    The shorthand form ``tracing: {enabled: true, to: local_files}`` is parsed
    into the canonical ``sinks`` list at validation time (D9); only the list
    shape exists downstream.

    D4/W6.2 — ``extra="forbid"``. W6.4 — ``enabled`` is tri-state
    (``None`` = unset / defer; the tracer treats unset as off).
    """

    model_config = ConfigDict(extra=_SECURITY_RUNTIME_EXTRA, populate_by_name=True)

    enabled: bool | None = None
    retention_days: int = Field(default=30, alias="retentionDays")
    sinks: list[TraceSinkEntry] = Field(default_factory=list)
    redaction: bool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_shorthand(cls, data: object) -> object:
        """Expand the ``to: <shorthand>`` form into the canonical ``sinks`` list.

        ``local_files`` expands to ``[{"type": "jsonl_file", "path": ".mergecraft/traces/"}]``;
        unknown shorthand values raise. The shorthand key is consumed and not
        preserved on the model — exactly one shape exists downstream.
        """
        if not isinstance(data, dict):
            return data
        shorthand = data.pop("to", None)
        if shorthand is None:
            return data
        if data.get("sinks"):
            return data
        if shorthand == "local_files":
            data["sinks"] = [{"type": "jsonl_file", "path": _SHORTHAND_LOCAL_FILES_DEFAULT_PATH}]
            return data
        msg = f"unknown tracing shorthand: {shorthand!r}"
        raise ValueError(msg)


class RepoSettings(BaseModel):
    """Per-repo runtime settings — local equivalent of upstream ``RepoSettings``.

    D4/W6.2 — ``extra="forbid"``: unknown top-level keys are configuration errors.
    """

    model_config = ConfigDict(extra=_SECURITY_RUNTIME_EXTRA, populate_by_name=True)

    model: str | None = None
    models: list[str] | None = None
    model_fallbacks: dict[str, list[str]] | None = Field(default=None, alias="modelFallbacks")
    # #37 / W4 / D8 — ``model_pin`` opts into the "use exactly this model"
    # semantics: when ``True``, supplying ``model:`` (or ``MERGECRAFT_MODEL``)
    # collapses the chain to a single entry instead of prepending it as the
    # chain head. Default ``False`` keeps the chain-preserving behaviour the
    # wave introduces — see ``utils/agent_resolve.py::effective_model_chain``.
    model_pin: bool = Field(default=False, alias="modelPin")
    # W10.1 / #20 — when ``False``, a retryable failure of the primary model
    # is a ``configuration_error`` instead of silently advancing the chain.
    # Default ``True`` preserves today's fallback behaviour.
    allow_fallback: bool = Field(default=True, alias="allowFallback")
    modes: list[ModeDefinition] = Field(default_factory=list)
    setup_script: str | None = Field(default=None, alias="setupScript")
    prepush_script: str | None = Field(default=None, alias="prepushScript")
    stop_script: str | None = Field(default=None, alias="stopScript")
    # S1 / D10 — ``setup_failure_policy`` decides what a trusted-tier
    # ``setup_script`` failure means. Closed vocabulary
    # (``inconclusive`` | ``fail`` | ``warn``); default ``inconclusive``
    # matches D5 — the run maps to ``RunOutcome.inconclusive`` rather than
    # passing a review of an under-provisioned tree. Unknown values fail
    # closed via the action-input resolver (``apply_setup_overrides``).
    setup_failure_policy: Literal["inconclusive", "fail", "warn"] = Field(
        default="inconclusive",
        alias="setupFailurePolicy",
    )
    # S1 / F6 — wall-clock budget for ``setup_script`` in seconds.
    # Always applied (even with ``--notimeout``); never consumes the whole
    # run deadline. Resolved from ``INPUT_SETUP_TIMEOUT`` via
    # ``action.inputs.apply_setup_overrides`` so the same parser the
    # ``timeout`` input uses covers both.
    setup_timeout_s: int = Field(default=600, alias="setupTimeout", gt=0)
    push: PushPermission = "restricted"
    shell: ShellPermission = "restricted"
    pr_approve_enabled: bool = Field(default=False, alias="prApproveEnabled")
    auto_merge_enabled: bool = Field(default=False, alias="autoMergeEnabled")
    blast_radius_override: RuleSet = Field(default_factory=RuleSet, alias="blastRadiusOverride")
    signed_commits: bool = Field(default=False, alias="signedCommits")
    mode_instructions: dict[str, str] = Field(default_factory=dict, alias="modeInstructions")
    static_checks: list[StaticCheckDefinition] = Field(default_factory=list, alias="staticChecks")
    # #36 / D10 — declared-only reuse of the repo's finished CI. Default empty:
    # no declaration, no substitution, no extra API call.
    ci_evidence: CiEvidenceSettings = Field(default_factory=CiEvidenceSettings, alias="ciEvidence")
    analyzers: AnalyzersSettings = Field(default_factory=AnalyzersSettings)
    learnings: str | None = None
    learnings_headings: list[LearningsHeading] = Field(
        default_factory=list, alias="learningsHeadings"
    )
    # D10 / W6.5 — opt-in auto-promote flag for new learning entries.
    # Default ``False`` (fail-closed): new entries land in the staging
    # section and only promote after an explicit approval call. Setting
    # this to ``True`` restores the legacy auto-promote behaviour for
    # trusted maintainer authors. See ``utils/learnings.py`` and #74.
    autopromote_learnings: bool = Field(default=False, alias="autopromoteLearnings")
    # W10.1 — gate-mode block. Every gate this plan introduces defaults
    # to ``shadow`` (D12). The override is layered on top of the default
    # policy at the gate; a mis-spelled value is rejected there.
    gates: GatesSettings = Field(default_factory=GatesSettings, alias="gates")
    env_allowlist: str | None = Field(default=None, alias="envAllowlist")
    # Extra GitHub logins (comma-separated) permitted to invoke mergeCraft by
    # comment even when ``comment.author_association`` is outside the trusted
    # set (D5 / W2.3). Default is empty = association gate only. Names are
    # matched case-insensitively against ``comment.user.login``.
    comment_invocation_allowlist: str | None = Field(
        default=None, alias="commentInvocationAllowlist"
    )
    xrepo_brief: str | None = Field(default=None, alias="xrepoBrief")
    xrepo_learnings: str | None = Field(default=None, alias="xrepoLearnings")
    xrepo_learnings_headings: list[LearningsHeading] = Field(
        default_factory=list, alias="xrepoLearningsHeadings"
    )
    tracing: TracingSettings = Field(default_factory=TracingSettings)

    @field_validator("push", "shell", mode="before")
    @classmethod
    def _normalize_permission(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower()
        return value


class RepoInfo(BaseModel):
    """GitHub repository identity plus raw ``repos.get`` payload."""

    model_config = ConfigDict(extra="ignore")

    owner: str
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunContextData(BaseModel):
    """Local run context — settings from disk + GitHub ``repos.get`` (no API token mint)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    repo: RepoInfo
    repo_settings: RepoSettings = Field(alias="repoSettings")
    api_token: str = Field(default="", alias="apiToken")
    oss: bool = False
    plan: AccountPlan = "none"
    proxy_model: str | None = Field(default=None, alias="proxyModel")
    db_secrets: dict[str, str] | None = Field(default=None, alias="dbSecrets")


_DEFAULT_CONFIG_REL = Path(".mergecraft") / "config.yaml"
_LEARNINGS_REL = Path(".mergecraft") / "learnings.md"
_XREPO_LEARNINGS_REL = Path(".mergecraft") / "xrepo-learnings.md"
_XREPO_BRIEF_REL = Path(".mergecraft") / "xrepo-brief.md"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def default_settings() -> RepoSettings:
    """Return upstream-matching default ``RepoSettings``."""
    return RepoSettings.model_validate(
        {
            "model": None,
            "models": None,
            "model_fallbacks": None,
            "modes": [],
            "setup_script": None,
            "prepush_script": None,
            "stop_script": None,
            "setup_failure_policy": "inconclusive",
            "setup_timeout_s": 600,
            "push": "restricted",
            "shell": "restricted",
            "pr_approve_enabled": False,
            "auto_merge_enabled": False,
            "blast_radius_override": {},
            "signed_commits": False,
            "mode_instructions": {},
            "static_checks": [],
            "analyzers": {},
            "learnings": None,
            "learnings_headings": [],
            "autopromote_learnings": False,
            "env_allowlist": None,
            "xrepo_brief": None,
            "xrepo_learnings": None,
            "xrepo_learnings_headings": [],
        }
    )


def parse_learnings_headings(body: str | None) -> list[LearningsHeading]:
    """Parse ATX headings (``#``-``######``) into TOC entries with 1-indexed ranges.

    Each heading's range starts at its own line and ends on the line before the
    next heading of equal or shallower depth (or EOF).
    """
    if not body:
        return []

    lines = body.splitlines()
    headings: list[tuple[int, int, str]] = []  # (line_1idx, depth, title)
    for idx, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        depth = len(match.group(1))
        title = match.group(2).strip()
        if title:
            headings.append((idx, depth, title))

    if not headings:
        return []

    last_line = len(lines)
    result: list[LearningsHeading] = []
    for i, (start, depth, title) in enumerate(headings):
        end = last_line
        for j in range(i + 1, len(headings)):
            next_start, next_depth, _ = headings[j]
            if next_depth <= depth:
                end = next_start - 1
                break
        result.append(
            LearningsHeading.model_validate(
                {
                    "depth": depth,
                    "title": title,
                    "startLine": start,
                    "endLine": max(start, end),
                }
            )
        )
    return result


def _workspace_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace)
    return Path.cwd()


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("failed to read {}: {}", path, exc)
        return None
    return text


def _resolve_config_path(
    path: Path | str | None = None, *, root: Path | None = None
) -> Path | None:
    if path is not None:
        candidate = Path(path)
        return candidate if candidate.is_file() else None

    env_path = os.environ.get("MERGECRAFT_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate
        logger.warning("MERGECRAFT_CONFIG set but file missing: {}", env_path)

    base = _workspace_root(root)
    candidate = base / _DEFAULT_CONFIG_REL
    if candidate.is_file():
        return candidate
    return None


def _merge_settings(raw: dict[str, Any] | None) -> RepoSettings:
    base = default_settings()
    if not raw:
        return base
    if analyzers := raw.get("analyzers"):
        from mergecraft.analyzers.registry import warn_unknown_analyzer_overrides

        warn_unknown_analyzer_overrides({"analyzers": analyzers})
    overlay = RepoSettings.model_validate(raw)
    unset = overlay.model_dump(exclude_unset=True)
    if not unset:
        return base
    merged = {**base.model_dump(), **unset}
    return RepoSettings.model_validate(merged)


def load_learnings(
    *,
    root: Path | None = None,
    learnings_path: Path | str | None = None,
) -> tuple[str | None, list[LearningsHeading]]:
    """Load ``.mergecraft/learnings.md`` (or ``learnings_path``) and parse TOC."""
    base = _workspace_root(root)
    path = Path(learnings_path) if learnings_path is not None else base / _LEARNINGS_REL
    body = _read_text(path)
    if body is None:
        return None, []
    return body, parse_learnings_headings(body)


def load_repo_settings(
    path: Path | str | None = None,
    *,
    root: Path | None = None,
    load_learnings_files: bool = True,
) -> RepoSettings:
    """Load repo settings from path, ``MERGECRAFT_CONFIG``, or ``.mergecraft/config.yaml``.

    When no config file exists, returns ``default_settings()``. Optionally merges
    learnings bodies + headings from ``.mergecraft/learnings.md`` (and xrepo files).
    """
    config_path = _resolve_config_path(path, root=root)
    raw: dict[str, Any] | None = None
    if config_path is not None:
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("failed to parse config {}: {}", config_path, exc)
            loaded = None
        if loaded is None:
            raw = {}
        elif not isinstance(loaded, dict):
            msg = f"config must be a mapping, got {type(loaded).__name__}: {config_path}"
            raise ValueError(msg)
        else:
            raw = loaded

    settings = _merge_settings(raw)

    if not load_learnings_files:
        return settings

    base = _workspace_root(root)
    learnings, headings = load_learnings(root=base)
    xrepo_learnings = _read_text(base / _XREPO_LEARNINGS_REL)
    xrepo_brief = _read_text(base / _XREPO_BRIEF_REL)

    update: dict[str, Any] = {}
    if learnings is not None:
        update["learnings"] = learnings
        update["learnings_headings"] = headings
    if xrepo_learnings is not None:
        update["xrepo_learnings"] = xrepo_learnings
        update["xrepo_learnings_headings"] = parse_learnings_headings(xrepo_learnings)
    if xrepo_brief is not None:
        update["xrepo_brief"] = xrepo_brief

    if update:
        settings = settings.model_copy(update=update)
    return settings
