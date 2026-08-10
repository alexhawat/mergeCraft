"""OpenAI-compatible Chat Completions API with tools (OpenAI, Nous, TokenHub, custom)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from meat_python_plus.model import Block, Message, Response, Role, Tool

MAX_OUTPUT_TOKENS = 16384
MAX_ATTEMPTS = 4
RETRY_BASE_DELAY = 1.0


class OpenAICompatModel:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        provider_name: str = "openai",
        timeout: float = 300.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name
        self.timeout = timeout

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> Response:
        url = self._chat_url()
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_messages(system, messages),
            "tools": self._to_tools(tools),
            "tool_choice": "auto",
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        # Some gateways prefer max_completion_tokens; keep max_tokens for broad compat.
        raw = self._post_json(url, body)
        return self._parse_response(raw)

    def _chat_url(self) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            return base + "/chat/completions"
        if base.endswith("/chat/completions"):
            return base
        return base + "/v1/chat/completions"

    def _to_tools(self, tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def _to_messages(self, system: str, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for msg in messages:
            if msg.role == Role.ASSISTANT:
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for b in msg.content:
                    if b.type == "text" and b.text:
                        text_parts.append(b.text)
                    elif b.type == "tool_use":
                        args = b.tool_input
                        if isinstance(args, str):
                            args_s = args
                        else:
                            args_s = json.dumps(args if args is not None else {})
                        tool_calls.append(
                            {
                                "id": b.id or f"call_{len(tool_calls)}",
                                "type": "function",
                                "function": {"name": b.tool_name, "arguments": args_s},
                            }
                        )
                am: dict[str, Any] = {"role": "assistant"}
                am["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    am["tool_calls"] = tool_calls
                out.append(am)
            else:
                # user / tool results
                text_parts = []
                for b in msg.content:
                    if b.type == "text":
                        text_parts.append(b.text)
                    elif b.type == "tool_result":
                        out.append(
                            {
                                "role": "tool",
                                "tool_call_id": b.tool_use_id,
                                "content": b.tool_result
                                if not b.tool_error
                                else f"ERROR: {b.tool_result}",
                            }
                        )
                if text_parts:
                    out.append({"role": "user", "content": "\n".join(text_parts)})
        return out

    def _parse_response(self, raw: dict[str, Any]) -> Response:
        if raw.get("error"):
            err = raw["error"]
            if isinstance(err, dict):
                raise RuntimeError(
                    f"{self.provider_name} error: {err.get('type', '')}: {err.get('message', err)}"
                )
            raise RuntimeError(f"{self.provider_name} error: {err}")

        usage = raw.get("usage") or {}
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError(f"{self.provider_name}: empty choices in response")
        message = choices[0].get("message") or {}
        content: list[Block] = []
        text = message.get("content")
        if text:
            content.append(Block(type="text", text=text))
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = args_raw
            content.append(
                Block(
                    type="tool_use",
                    id=str(tc.get("id") or ""),
                    tool_name=str(fn.get("name") or ""),
                    tool_input=args,
                )
            )
        finish = choices[0].get("finish_reason")
        if finish == "length":
            raise RuntimeError(
                f"{self.provider_name} response truncated at max_tokens "
                f"({MAX_OUTPUT_TOKENS}); the diff may be too large"
            )
        return Response(
            content=content,
            input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            output_tokens=int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            ),
        )

    def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        last_err: Exception | None = None
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }
        # TokenHub / some gateways also accept api-key style headers; Bearer is enough.
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
                    f"{self.provider_name} API {resp.status_code}: {resp.text.strip()}"
                )
                if resp.status_code not in (408, 429) and resp.status_code < 500:
                    raise last_err
            except httpx.HTTPError as e:
                last_err = e
        raise RuntimeError(f"after {MAX_ATTEMPTS} attempts: {last_err}")
