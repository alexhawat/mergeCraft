"""Pydantic models for provider-harness fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ProfileName = Literal[
    "http_429",
    "http_500",
    "http_401",
    "timeout",
    "malformed_json",
    "empty_stream",
    "disconnect_after_chunk",
]


class MalformedFixtureError(ValueError):
    """Raised when a fixture file or inline spec is invalid."""


class MatchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    mode: str | None = None
    streaming: bool = False
    turn_index: int = 0
    has_tool_results: bool | None = None
    test_context_id: str | None = None
    tool_call_id: str | None = None
    tool_result_content: str | None = None
    body_fields: dict[str, object] = Field(default_factory=dict)


class ResponseBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text", "tool_call"]
    text: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    arguments: dict[str, object] | None = None


class ResponseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_code: int = 200
    headers: dict[str, str] = Field(default_factory=dict)
    body: object | None = None
    blocks: list[ResponseBlock] = Field(default_factory=list)
    usage: dict[str, int] | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    delay_ms: int = 0

    @model_validator(mode="after")
    def _body_or_blocks(self) -> ResponseSpec:
        if self.body is None and not self.blocks:
            msg = "response must include body or blocks"
            raise ValueError(msg)
        return self


class FixtureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    match: MatchSpec
    response: ResponseSpec
    max_uses: int = 1
    profile: ProfileName | None = None


def load_fixture_file(path: Path) -> FixtureSpec:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MalformedFixtureError(f"{path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedFixtureError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedFixtureError(f"{path}: fixture root must be a JSON object")
    try:
        return FixtureSpec.model_validate(data)
    except ValidationError as exc:
        raise MalformedFixtureError(f"{path}: {exc}") from exc
