"""Tests for action payload resolution."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import default_settings
from mergecraft.utils.payload import (
    JsonPayload,
    resolve_native_event,
    resolve_output_schema,
    resolve_payload,
    resolve_prompt_input,
    validate_compatibility,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_json_payload_requires_marker() -> None:
    payload = JsonPayload.model_validate(
        {"~mergecraft": True, "version": "0.0.1", "prompt": "hello"}
    )
    assert payload.mergecraft is True
    assert payload.prompt == "hello"
    with pytest.raises(ValidationError):
        JsonPayload.model_validate({"version": "0.0.1", "prompt": "x"})


def test_resolve_prompt_input_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_PROMPT", "fix the bug")
    monkeypatch.delenv("INPUT_PROMPT_FILE", raising=False)
    assert resolve_prompt_input() == "fix the bug"


def test_resolve_prompt_input_json_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INPUT_PROMPT",
        json.dumps({"~mergecraft": True, "version": "0.0.1", "prompt": "from json"}),
    )
    monkeypatch.delenv("INPUT_PROMPT_FILE", raising=False)
    resolved = resolve_prompt_input()
    assert isinstance(resolved, JsonPayload)
    assert resolved.prompt == "from json"


def test_resolve_prompt_input_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("file prompt", encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("INPUT_PROMPT", raising=False)
    monkeypatch.setenv("INPUT_PROMPT_FILE", "prompt.md")
    assert resolve_prompt_input() == "file prompt"


def test_resolve_payload_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_PROMPT", "do work")
    monkeypatch.setenv("INPUT_SHELL", "restricted")
    monkeypatch.setenv("INPUT_PUSH", "enabled")
    monkeypatch.setenv("INPUT_STATUS_CHECKS", "enabled")
    monkeypatch.delenv("INPUT_PROMPT_FILE", raising=False)
    monkeypatch.delenv("INPUT_TIMEOUT", raising=False)
    monkeypatch.delenv("INPUT_MODEL", raising=False)
    monkeypatch.delenv("INPUT_CWD", raising=False)
    # No native GH event — expect the 'unknown' trigger fallback.
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    settings = default_settings()
    settings = settings.model_copy(update={"shell": "enabled", "model": "anthropic/claude-opus"})
    payload = resolve_payload(repo_settings=settings)

    assert payload["~mergecraft"] is True
    assert payload["prompt"] == "do work"
    assert payload["shell"] == "restricted"  # input made it stricter
    assert payload["push"] == "enabled"
    assert payload["statusChecks"] is True
    assert payload["model"] == "anthropic/claude-opus"
    assert payload["event"]["trigger"] == "unknown"


def test_resolve_payload_non_collaborator_cannot_enable_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "INPUT_PROMPT",
        json.dumps(
            {
                "~mergecraft": True,
                "version": "0.0.1",
                "prompt": "hi",
                "event": {"trigger": "issues_opened", "authorPermission": "read"},
            }
        ),
    )
    monkeypatch.delenv("INPUT_PROMPT_FILE", raising=False)
    monkeypatch.delenv("INPUT_SHELL", raising=False)
    settings = default_settings().model_copy(update={"shell": "enabled"})
    payload = resolve_payload(repo_settings=settings)
    assert payload["shell"] == "restricted"


def test_resolve_output_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_OUTPUT_SCHEMA", '{"type":"object"}')
    assert resolve_output_schema() == {"type": "object"}
    with pytest.raises(ValueError, match="not valid JSON"):
        resolve_output_schema("{")
    with pytest.raises(ValueError, match="JSON object"):
        resolve_output_schema("[1]")


def _write_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, body: dict) -> None:
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", name)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))


def test_resolve_native_event_none_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert resolve_native_event() is None


def test_resolve_native_event_pull_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_event(
        tmp_path,
        monkeypatch,
        "pull_request",
        {
            "action": "synchronize",
            "number": 42,
            "before": "abc123",
            "pull_request": {
                "number": 42,
                "title": "Add widget",
                "body": "body text",
                "head": {"ref": "feature/widget"},
            },
        },
    )
    event = resolve_native_event()
    assert event is not None
    assert event["trigger"] == "pull_request_synchronize"
    assert event["issue_number"] == 42
    assert event["is_pr"] is True
    assert event["branch"] == "feature/widget"
    assert event["before_sha"] == "abc123"


def test_resolve_native_event_pr_opened_maps_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(
        tmp_path,
        monkeypatch,
        "pull_request",
        {"action": "opened", "number": 7, "pull_request": {"number": 7, "head": {"ref": "x"}}},
    )
    event = resolve_native_event()
    assert event is not None
    assert event["trigger"] == "pull_request_opened"


def test_resolve_native_event_issue_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(
        tmp_path,
        monkeypatch,
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 9, "title": "T", "pull_request": {"url": "..."}},
            "comment": {"id": 555, "body": "@mergecraft review"},
        },
    )
    event = resolve_native_event()
    assert event is not None
    assert event["trigger"] == "issue_comment_created"
    assert event["issue_number"] == 9
    assert event["is_pr"] is True
    assert event["comment_id"] == 555


def test_resolve_native_event_workflow_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(tmp_path, monkeypatch, "workflow_dispatch", {})
    assert resolve_native_event() == {"trigger": "workflow_dispatch"}


def test_resolve_payload_uses_native_pull_request_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_PROMPT", "Review this PR")
    monkeypatch.setenv("INPUT_STATUS_CHECKS", "enabled")
    for var in ("INPUT_PROMPT_FILE", "INPUT_SHELL", "INPUT_PUSH", "INPUT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    _write_event(
        tmp_path,
        monkeypatch,
        "pull_request",
        {"action": "opened", "number": 5, "pull_request": {"number": 5, "head": {"ref": "b"}}},
    )
    payload = resolve_payload()
    assert payload["event"]["trigger"] == "pull_request_opened"
    assert payload["event"]["issue_number"] == 5
    assert payload["event"]["is_pr"] is True
    assert payload["statusChecks"] is True


def test_validate_compatibility() -> None:
    validate_compatibility("0.0.1", "0.0.2")
    validate_compatibility("1.0.0", "1.2.0")
    with pytest.raises(ValueError, match="incompatible"):
        validate_compatibility("0.1.0", "0.2.0")
    with pytest.raises(ValueError, match="not a valid"):
        validate_compatibility("nope", "0.0.1")
