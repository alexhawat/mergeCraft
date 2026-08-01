"""Action input / JSON payload resolution (INPUT_* env + ~mergecraft marker)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal, cast

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft import __version__
from mergecraft.config.settings import RepoSettings
from mergecraft.types import AuthorPermission, PushPermission, ShellPermission, XrepoConfig
from mergecraft.utils.time_parse import (
    TIMEOUT_DISABLED,
    normalize_timeout_input,
    parse_timeout,
    resolve_timeout_ms,
)

StatusChecksInput = Literal["disabled", "enabled"]
ProgressCommentType = Literal["issue", "review"]

COLLABORATOR_PERMISSIONS: frozenset[AuthorPermission] = frozenset({"admin", "maintain", "write"})

PayloadTrigger = Literal[
    "pull_request_opened",
    "pull_request_ready_for_review",
    "pull_request_synchronize",
    "pull_request_review_requested",
    "pull_request_review_submitted",
    "pull_request_review_comment_created",
    "issues_opened",
    "issues_assigned",
    "issues_labeled",
    "issue_comment_created",
    "check_suite_completed",
    "workflow_dispatch",
    "fix_review",
    "implement_plan",
    "unknown",
]


class PayloadEvent(BaseModel):
    """Discriminated-ish event payload; extra fields preserved for trigger variants."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    trigger: str = "unknown"
    issue_number: int | None = None
    is_pr: bool | None = None
    branch: str | None = None
    title: str | None = None
    body: str | None = None
    comment_id: int | None = None
    review_id: int | None = None
    review_state: str | None = None
    author_permission: AuthorPermission | None = Field(default=None, alias="authorPermission")
    silent: bool | None = None
    plan_comment_id: int | None = None
    before_sha: str | None = None
    comment_type: str | None = None
    approved_only: bool | None = None


class ProgressComment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: ProgressCommentType


class JsonPayload(BaseModel):
    """Internal dispatch JSON payload — requires ``~mergecraft: true`` marker.

    Permissions are intentionally NOT included here (injection surface); they are
    derived from ``event.authorPermission`` / action inputs / repo settings.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    mergecraft: Literal[True] = Field(alias="~mergecraft")
    version: str
    prompt: str
    model: str | None = None
    model_explicit: bool | None = Field(default=None, alias="modelExplicit")
    triggerer: str | None = None
    base_instructions: str | None = Field(default=None, alias="baseInstructions")
    event_instructions: str | None = Field(default=None, alias="eventInstructions")
    previous_runs_note: str | None = Field(default=None, alias="previousRunsNote")
    event: dict[str, Any] | None = None
    xrepo: XrepoConfig | None = None
    timeout: str | None = None
    progress_comment: ProgressComment | None = Field(default=None, alias="progressComment")
    generate_summary: bool | None = Field(default=None, alias="generateSummary")


class ActionInputs(BaseModel):
    """Workflow action inputs (from ``INPUT_*`` env vars)."""

    model_config = ConfigDict(extra="ignore")

    prompt: str | None = None
    prompt_file: str | None = None
    model: str | None = None
    timeout: str | None = None
    push: PushPermission | None = None
    shell: ShellPermission | None = None
    status_checks: StatusChecksInput | None = None
    cwd: str | None = None
    output_schema: str | None = None
    analyzers: str | None = None

    @field_validator("push", "shell", "status_checks", "analyzers", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        if isinstance(value, str):
            return value.lower()
        return value


def _package_version() -> str:
    return __version__


def get_action_input(name: str) -> str:
    """Read a GitHub Actions input from ``INPUT_<NAME>`` (uppercase)."""
    env_key = "INPUT_" + name.upper().replace("-", "_")
    return os.environ.get(env_key, "").strip()


def is_mergecraft(actor: str | None) -> bool:
    """True when ``actor`` is mergeCraft's own GitHub identity."""
    if not actor:
        return False
    cleaned = actor.replace("[bot]", "")
    return cleaned in {"mergecraft", "mergecraftdev"}


def is_collaborator(event: PayloadEvent) -> bool:
    perm = event.author_permission
    return perm is not None and perm in COLLABORATOR_PERMISSIONS


def is_payload_event(value: object) -> bool:
    return isinstance(value, dict) and "trigger" in value


# GitHub `pull_request` action -> internal trigger. Actions not listed here
# (e.g. closed, labeled) fall back to the synchronize trigger since the agent
# still reviews the current head.
_PR_ACTION_TRIGGERS: dict[str, str] = {
    "opened": "pull_request_opened",
    "reopened": "pull_request_opened",
    "ready_for_review": "pull_request_ready_for_review",
    "synchronize": "pull_request_synchronize",
    "review_requested": "pull_request_review_requested",
}


def _read_github_event() -> dict[str, Any] | None:
    """Load and parse ``GITHUB_EVENT_PATH`` (the native GitHub Actions event)."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read GITHUB_EVENT_PATH {}: {}", path, exc)
        return None
    return data if isinstance(data, dict) else None


def read_github_event() -> dict[str, Any] | None:
    """Public alias for native GitHub Actions event payload."""
    return _read_github_event()


def _head_ref(pr: dict[str, Any]) -> str | None:
    head = pr.get("head")
    return head.get("ref") if isinstance(head, dict) else None


def resolve_native_event() -> dict[str, Any] | None:
    """Build a ``PayloadEvent``-shaped dict from the native GitHub Actions event.

    Reads ``GITHUB_EVENT_NAME`` + ``GITHUB_EVENT_PATH`` so a workflow that triggers
    on native ``pull_request`` / ``issue_comment`` / ``pull_request_review_comment``
    events gives the agent PR context (and lets ``report_status_checks`` fire)
    without the caller hand-building a ``~mergecraft`` JSON payload. Returns ``None``
    when there is no usable context, so callers fall back to the ``unknown``
    trigger — preserving prior behavior for local / non-Actions runs.
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME") or ""
    if not event_name:
        return None
    data = _read_github_event()
    if data is None:
        return None
    action = str(data.get("action") or "")

    if event_name in {"pull_request", "pull_request_target"}:
        pr = data.get("pull_request")
        if not isinstance(pr, dict):
            return None
        number = data.get("number") or pr.get("number")
        if number is None:
            return None
        return {
            "trigger": _PR_ACTION_TRIGGERS.get(action, "pull_request_synchronize"),
            "issue_number": int(number),
            "is_pr": True,
            "branch": _head_ref(pr),
            "title": pr.get("title"),
            "body": pr.get("body"),
            "before_sha": data.get("before"),
        }

    if event_name == "pull_request_review_comment":
        pr = data.get("pull_request")
        if not isinstance(pr, dict) or pr.get("number") is None:
            return None
        comment = data.get("comment")
        comment = comment if isinstance(comment, dict) else {}
        return {
            "trigger": "pull_request_review_comment_created",
            "issue_number": int(pr["number"]),
            "is_pr": True,
            "branch": _head_ref(pr),
            "comment_id": comment.get("id"),
            "body": comment.get("body"),
        }

    if event_name == "issue_comment":
        issue = data.get("issue")
        if not isinstance(issue, dict) or issue.get("number") is None:
            return None
        comment = data.get("comment")
        comment = comment if isinstance(comment, dict) else {}
        return {
            "trigger": "issue_comment_created",
            "issue_number": int(issue["number"]),
            "is_pr": issue.get("pull_request") is not None,
            "title": issue.get("title"),
            "comment_id": comment.get("id"),
            "body": comment.get("body"),
        }

    if event_name == "workflow_dispatch":
        return {"trigger": "workflow_dispatch"}

    return None


def resolve_cwd(cwd: str | None) -> str | None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not cwd:
        return workspace
    path = Path(cwd)
    if path.is_absolute():
        return str(path)
    if workspace:
        return str(Path(workspace) / cwd)
    return cwd


def resolve_prompt_file(input_path: str) -> str:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    path = Path(input_path)
    if not path.is_absolute():
        path = Path(workspace, input_path) if workspace else Path(input_path).resolve()
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        msg = f"prompt_file {input_path!r} is empty."
        raise ValueError(msg)
    return content


def validate_compatibility(payload_version: str, action_version: str) -> None:
    """Enforce non-breaking semver compatibility between payload and action.

    Mirrors upstream ``COMPATIBILITY_POLICY = "non-breaking"``:
    - ``0.x``: same minor required
    - ``>=1``: same major required
    """
    import semver

    try:
        payload_semver = semver.Version.parse(payload_version)
        action_semver = semver.Version.parse(action_version)
    except ValueError as exc:
        msg = f"Payload version {payload_version} is not a valid semantic version."
        raise ValueError(msg) from exc

    major = payload_semver.major
    minor = payload_semver.minor
    compatible = (major == 0 and action_semver.major == 0 and action_semver.minor == minor) or (
        major >= 1 and action_semver.major == major
    )
    if not compatible:
        msg = (
            f"Payload version {payload_version} is incompatible with action version "
            f"{action_version}."
        )
        raise ValueError(msg)


def resolve_prompt_input(
    *,
    prompt: str | None = None,
    prompt_file: str | None = None,
) -> str | JsonPayload:
    """Resolve ``prompt`` / ``prompt_file`` into plain text or a validated ``JsonPayload``."""
    prompt_input = prompt if prompt is not None else get_action_input("prompt")
    file_input = prompt_file if prompt_file is not None else get_action_input("prompt_file")

    if prompt_input and file_input:
        msg = "set exactly one of 'prompt' or 'prompt_file' inputs, not both."
        raise ValueError(msg)

    if file_input:
        return resolve_prompt_file(file_input)

    if not prompt_input:
        msg = "one of 'prompt' or 'prompt_file' inputs is required."
        raise ValueError(msg)

    try:
        parsed: object = json.loads(prompt_input)
    except json.JSONDecodeError:
        return prompt_input

    if not isinstance(parsed, dict) or "~mergecraft" not in parsed:
        return prompt_input

    json_payload = JsonPayload.model_validate(parsed)
    validate_compatibility(json_payload.version, _package_version())
    return json_payload


def resolve_non_prompt_inputs() -> ActionInputs:
    return ActionInputs.model_validate(
        {
            "model": get_action_input("model") or None,
            "timeout": get_action_input("timeout") or None,
            "cwd": get_action_input("cwd") or None,
            "push": get_action_input("push") or None,
            "shell": get_action_input("shell") or None,
            "status_checks": get_action_input("status_checks") or None,
        }
    )


def _stricter_shell(
    repo_shell: ShellPermission,
    input_shell: ShellPermission | None,
    *,
    non_collaborator: bool,
) -> ShellPermission:
    """Strictest wins: disabled > restricted > enabled."""
    resolved: ShellPermission = repo_shell
    if input_shell == "disabled":
        resolved = "disabled"
    elif input_shell == "restricted" and resolved == "enabled":
        resolved = "restricted"
    if non_collaborator and resolved == "enabled":
        resolved = "restricted"
    return resolved


def resolve_payload(
    resolved_prompt_input: str | JsonPayload | None = None,
    repo_settings: RepoSettings | None = None,
) -> dict[str, Any]:
    """Build the runtime payload from prompt input + action inputs + repo settings."""
    settings = repo_settings or RepoSettings()
    if resolved_prompt_input is None:
        resolved_prompt_input = resolve_prompt_input()

    if isinstance(resolved_prompt_input, JsonPayload):
        prompt = resolved_prompt_input.prompt
        json_payload: JsonPayload | None = resolved_prompt_input
    else:
        prompt = resolved_prompt_input
        json_payload = None

    inputs = resolve_non_prompt_inputs()

    raw_event = json_payload.event if json_payload else None
    if not is_payload_event(raw_event):
        # No explicit ~mergecraft event — derive it from the native GH Actions event.
        raw_event = resolve_native_event()
    event = (
        PayloadEvent.model_validate(raw_event)
        if is_payload_event(raw_event)
        else PayloadEvent(trigger="unknown")
    )

    model = (json_payload.model if json_payload else None) or inputs.model or settings.model or None

    repo_shell: ShellPermission = settings.shell or "restricted"
    resolved_shell = _stricter_shell(
        repo_shell,
        inputs.shell,
        non_collaborator=not is_collaborator(event),
    )

    timeout_raw = inputs.timeout or (json_payload.timeout if json_payload else None)
    timeout = normalize_timeout_input(timeout_raw)

    github_actor = os.environ.get("GITHUB_ACTOR")
    triggerer = (json_payload.triggerer if json_payload else None) or (
        github_actor if not is_mergecraft(github_actor) else None
    )

    return {
        "~mergecraft": True,
        "version": (json_payload.version if json_payload else None) or _package_version(),
        "model": model,
        "modelExplicit": (json_payload.model_explicit if json_payload else None) or False,
        "prompt": prompt,
        "triggerer": triggerer,
        "baseInstructions": json_payload.base_instructions if json_payload else None,
        "eventInstructions": json_payload.event_instructions if json_payload else None,
        "previousRunsNote": json_payload.previous_runs_note if json_payload else None,
        "event": event.model_dump(by_alias=True, exclude_none=False),
        "xrepo": (json_payload.xrepo.model_dump() if json_payload and json_payload.xrepo else None),
        "timeout": timeout,
        "cwd": resolve_cwd(inputs.cwd),
        "progressComment": (
            json_payload.progress_comment.model_dump()
            if json_payload and json_payload.progress_comment
            else None
        ),
        "generateSummary": json_payload.generate_summary if json_payload else None,
        "push": inputs.push or settings.push or "restricted",
        "shell": resolved_shell,
        "statusChecks": inputs.status_checks == "enabled",
        "proxyModel": None,
    }


def resolve_output_schema(raw: str | None = None) -> dict[str, Any] | None:
    """Parse optional ``output_schema`` action input into a JSON object."""
    value = raw if raw is not None else get_action_input("output_schema")
    if not value:
        return None
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError as exc:
        msg = "invalid output_schema: not valid JSON"
        raise ValueError(msg) from exc
    if not isinstance(parsed, dict):
        msg = "invalid output_schema: must be a JSON object"
        raise ValueError(msg)
    logger.info("» structured output schema provided — output will be required")
    return cast("dict[str, Any]", parsed)


__all__ = [
    "TIMEOUT_DISABLED",
    "ActionInputs",
    "AuthorPermission",
    "JsonPayload",
    "PayloadEvent",
    "ProgressComment",
    "PushPermission",
    "ShellPermission",
    "XrepoConfig",
    "get_action_input",
    "is_collaborator",
    "is_mergecraft",
    "normalize_timeout_input",
    "parse_timeout",
    "read_github_event",
    "resolve_cwd",
    "resolve_native_event",
    "resolve_non_prompt_inputs",
    "resolve_output_schema",
    "resolve_payload",
    "resolve_prompt_input",
    "resolve_timeout_ms",
    "validate_compatibility",
]
