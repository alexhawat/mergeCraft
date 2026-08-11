"""Anthropic Messages API with tools."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from meat_python_plus.model import Block, Message, Response, Role, Tool

MAX_OUTPUT_TOKENS = 16384
MAX_ATTEMPTS = 4
RETRY_BASE_DELAY = 1.0


class AnthropicMessagesModel:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> Response:
        url = self.base_url + "/v1/messages"
        body = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": self._to_messages(messages),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ],
        }
        raw = self._post_json(url, body)
        if raw.get("error"):
            err = raw["error"]
            raise RuntimeError(
                f"anthropic error: {err.get('type', '')}: {err.get('message', err)}"
            )
        if raw.get("stop_reason") == "max_tokens":
            raise RuntimeError(
                f"anthropic response truncated at max_tokens ({MAX_OUTPUT_TOKENS})"
            )
        content: list[Block] = []
        for b in raw.get("content") or []:
            btype = b.get("type")
            if btype == "text":
                content.append(Block(type="text", text=b.get("text") or ""))
            elif btype == "tool_use":
                content.append(
                    Block(
                        type="tool_use",
                        id=str(b.get("id") or ""),
                        tool_name=str(b.get("name") or ""),
                        tool_input=b.get("input") or {},
                    )
                )
        usage = raw.get("usage") or {}
        return Response(
            content=content,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )

    def _to_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            blocks: list[dict[str, Any]] = []
            for b in msg.content:
                if b.type == "text":
                    blocks.append({"type": "text", "text": b.text})
                elif b.type == "tool_use":
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": b.id,
                            "name": b.tool_name,
                            "input": b.tool_input
                            if isinstance(b.tool_input, dict)
                            else json.loads(b.tool_input or "{}"),
                        }
                    )
                elif b.type == "tool_result":
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.tool_use_id,
                            "content": b.tool_result,
                            "is_error": b.tool_error,
                        }
                    )
            role = "assistant" if msg.role == Role.ASSISTANT else "user"
            out.append({"role": role, "content": blocks})
        return out

    def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        last_err: Exception | None = None
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(MAX_ATTEMPTS):
            if attempt > 0:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, content=payload, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
                last_err = RuntimeError(
                    f"anthropic API {resp.status_code}: {resp.text.strip()}"
                )
                if resp.status_code not in (408, 429) and resp.status_code < 500:
                    raise last_err
            except httpx.HTTPError as e:
                last_err = e
        raise RuntimeError(f"after {MAX_ATTEMPTS} attempts: {last_err}")
