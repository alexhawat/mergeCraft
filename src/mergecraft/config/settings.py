"""Local repo settings, learnings TOC, and run-context assembly (no mergecraft.com API)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.types import PushPermission, ShellPermission  # noqa: TC001

AccountPlan = Literal["none", "payg"]
HeadingDepth = Literal[1, 2, 3, 4, 5, 6]


class ModeDefinition(BaseModel):
    """Custom / built-in mode selectable via ``select_mode``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    description: str
    prompt: str = ""


class LearningsHeading(BaseModel):
    """TOC entry for a learnings markdown body (1-indexed line ranges)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    depth: HeadingDepth
    title: str
    start_line: int = Field(alias="startLine")
    end_line: int = Field(alias="endLine")


class StaticCheckDefinition(BaseModel):
    """A mechanical gate the repo declares for reviewers to run.

    ``command`` may contain a ``{files}`` token, replaced with the diff's changed
    paths. ``suffixes`` restricts the gate to diffs that touch matching files.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    command: str
    suffixes: list[str] = Field(default_factory=list)


class AnalyzerOverride(BaseModel):
    """Per-analyzer config override."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool | None = None


class AnalyzerPatternSettings(BaseModel):
    """Pattern backend selection for analyzer detection."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    backend: str | None = None


class AnalyzersSettings(BaseModel):
    """Catalog analyzer configuration block."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = True
    inline_budget: int = Field(default=8, alias="inlineBudget")
    base_comparison: str = Field(default="diff", alias="baseComparison")
    overrides: dict[str, AnalyzerOverride] = Field(default_factory=dict)
    pattern: AnalyzerPatternSettings = Field(default_factory=AnalyzerPatternSettings)


class RepoSettings(BaseModel):
    """Per-repo runtime settings — local equivalent of upstream ``RepoSettings``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    model: str | None = None
    models: list[str] | None = None
    model_fallbacks: dict[str, list[str]] | None = Field(default=None, alias="modelFallbacks")
    modes: list[ModeDefinition] = Field(default_factory=list)
    setup_script: str | None = Field(default=None, alias="setupScript")
    post_checkout_script: str | None = Field(default=None, alias="postCheckoutScript")
    prepush_script: str | None = Field(default=None, alias="prepushScript")
    stop_script: str | None = Field(default=None, alias="stopScript")
    push: PushPermission = "restricted"
    shell: ShellPermission = "restricted"
    pr_approve_enabled: bool = Field(default=False, alias="prApproveEnabled")
    auto_merge_enabled: bool = Field(default=False, alias="autoMergeEnabled")
    signed_commits: bool = Field(default=False, alias="signedCommits")
    mode_instructions: dict[str, str] = Field(default_factory=dict, alias="modeInstructions")
    static_checks: list[StaticCheckDefinition] = Field(default_factory=list, alias="staticChecks")
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
    env_allowlist: str | None = Field(default=None, alias="envAllowlist")
    xrepo_brief: str | None = Field(default=None, alias="xrepoBrief")
    xrepo_learnings: str | None = Field(default=None, alias="xrepoLearnings")
    xrepo_learnings_headings: list[LearningsHeading] = Field(
        default_factory=list, alias="xrepoLearningsHeadings"
    )

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
            "post_checkout_script": None,
            "prepush_script": None,
            "stop_script": None,
            "push": "restricted",
            "shell": "restricted",
            "pr_approve_enabled": False,
            "auto_merge_enabled": False,
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
