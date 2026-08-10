"""Provider-agnostic model types for the abridge agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class Role:
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    tool_name: str = ""
    tool_input: Any = None  # dict or raw JSON-compatible
    tool_use_id: str = ""
    tool_result: str = ""
    tool_error: bool = False
    provider: str = ""
    provider_data: Any = None


@dataclass
class Message:
    role: str
    content: list[Block] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Response:
    content: list[Block] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class Model(Protocol):
    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> Response: ...


def text_block(s: str) -> Block:
    return Block(type="text", text=s)
