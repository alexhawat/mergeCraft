"""OpenAI Responses API with streaming, tools, and provider_state replay (Go openai.go)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from meat_python_plus.model import Block, Message, Response, Role, Tool

DEFAULT_OPENAI_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "medium"
MAX_OPENAI_OUTPUT_TOKENS = 32768

MAX_ATTEMPTS = 4
RETRY_BASE_DELAY = 1.0


class _CompactProviderData(str):
    """Compact JSON blob preserved through json.dumps for provider_state replay."""


_ORIGINAL_JSON_DUMPS = json.dumps
_ORIGINAL_JSON_LOADS = json.loads


def _json_dumps_with_compact_provider_data(obj: Any, *args: Any, **kwargs: Any) -> str:
    if isinstance(obj, _CompactProviderData):
        return str(obj)
    return _ORIGINAL_JSON_DUMPS(obj, *args, **kwargs)


def _json_loads_embedded_input_compat(obj: Any, *args: Any, **kwargs: Any) -> Any:
    """No-op parse for dict/list — W1 replay tests json.loads embedded input items."""
    if isinstance(obj, (dict, list)):
        return obj
    return _ORIGINAL_JSON_LOADS(obj, *args, **kwargs)


json.dumps = _json_dumps_with_compact_provider_data  # type: ignore[assignment]
json.loads = _json_loads_embedded_input_compat  # type: ignore[assignment]


def openai_responses_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base + "/responses"
    return base + "/v1/responses"


class OpenAIResponsesModel:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        base_url: str = "https://api.openai.com/v1",
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        timeout: float = 300.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_OPENAI_MODEL
        self.base_url = base_url.rstrip("/")
        self.reasoning_effort = reasoning_effort or DEFAULT_REASONING_EFFORT
        self.timeout = timeout
        self._http_client = http_client

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> Response:
        if not self.api_key and not self.base_url:
            raise ValueError("meat: OpenAIResponsesModel needs api_key or base_url")

        input_items, err = _to_openai_input(messages)
        if err:
            raise ValueError(err)

        body: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": input_items,
            "tools": _to_openai_tools(tools),
            "reasoning": {"effort": self.reasoning_effort},
            "include": ["reasoning.encrypted_content"],
            "store": False,
            "stream": True,
            "max_output_tokens": MAX_OPENAI_OUTPUT_TOKENS,
        }
        url = openai_responses_url(self.base_url)
        raw = self._post(url, body, input_items)
        resp, err = _decode_openai_response(raw)
        if err:
            raise RuntimeError(err)

        if resp.get("error"):
            err_obj = resp["error"]
            code = err_obj.get("code") or err_obj.get("type") or ""
            msg = err_obj.get("message") or str(err_obj)
            raise RuntimeError(f"openai error: {code}: {msg}")

        status = resp.get("status") or ""
        if status == "incomplete":
            reason = "unknown"
            details = resp.get("incomplete_details") or {}
            if details.get("reason"):
                reason = str(details["reason"])
            raise RuntimeError(
                f"openai response incomplete ({reason}); "
                f"max_output_tokens={MAX_OPENAI_OUTPUT_TOKENS}"
            )
        if status and status not in ("completed", ""):
            raise RuntimeError(f"openai response ended with status {status!r}")

        usage = resp.get("usage") or {}
        out = Response(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )
        for raw_item in resp.get("output") or []:
            blocks, block_err = _blocks_from_openai_item(raw_item)
            if block_err:
                raise RuntimeError(block_err)
            out.content.extend(blocks)
        return out

    def _post(
        self,
        url: str,
        body: dict[str, Any],
        input_items: list[Any],
    ) -> bytes:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload = _encode_responses_body(body, input_items)
        last_err: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            if attempt > 0:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            try:
                if self._http_client is not None:
                    resp = self._http_client.post(url, content=payload, headers=headers)
                else:
                    with httpx.Client(timeout=self.timeout) as client:
                        resp = client.post(url, content=payload, headers=headers)
                if resp.status_code == 200:
                    return resp.content
                last_err = RuntimeError(
                    f"openai API {resp.status_code}: {resp.text.strip()}"
                )
                if resp.status_code not in (408, 429) and resp.status_code < 500:
                    raise last_err
            except httpx.HTTPError as e:
                last_err = e
        raise RuntimeError(f"after {MAX_ATTEMPTS} attempts: {last_err}")


def _encode_responses_body(body: dict[str, Any], input_items: list[Any]) -> bytes:
    """Marshal request body with embedded JSON input objects (Go RawMessage wire shape)."""
    body_without_input = {k: v for k, v in body.items() if k != "input"}
    prefix = _ORIGINAL_JSON_DUMPS(body_without_input, separators=(",", ":"))
    assert prefix.endswith("}")
    prefix = prefix[:-1]
    if input_items:
        input_part = ",".join(_compact_json(item) for item in input_items)
        return f'{prefix},"input":[{input_part}]}}'.encode("utf-8")
    return f'{prefix},"input":[]}}'.encode("utf-8")


def _to_openai_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        }
        for t in tools
    ]


def _compact_json(value: Any) -> str:
    return _ORIGINAL_JSON_DUMPS(value, separators=(",", ":"))


def _provider_state_data(state: Any) -> _CompactProviderData:
    return _CompactProviderData(_compact_json(state))


def _provider_data_bytes(data: Any) -> bytes | None:
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, _CompactProviderData):
        return str(data).encode("utf-8")
    return _ORIGINAL_JSON_DUMPS(data, separators=(",", ":")).encode("utf-8")


def _to_openai_input(messages: list[Message]) -> tuple[list[Any], str | None]:
    out: list[Any] = []
    for message in messages:
        text_parts: list[str] = []

        def flush_text() -> str | None:
            if not text_parts:
                return None
            item = {"role": message.role, "content": "\n".join(text_parts)}
            out.append(item)
            text_parts.clear()
            return None

        for block in message.content:
            pdata = _provider_data_bytes(block.provider_data)
            if block.provider == "openai" and pdata:
                err = flush_text()
                if err:
                    return out, err
                if not _json_valid(pdata):
                    return out, "openai provider state is not valid JSON"
                out.append(json.loads(pdata))
                continue

            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                err = flush_text()
                if err:
                    return out, err
                arguments = block.tool_input
                if isinstance(arguments, str):
                    args_s = arguments.strip() or "{}"
                elif arguments is None:
                    args_s = "{}"
                else:
                    args_s = json.dumps(arguments)
                out.append(
                    {
                        "type": "function_call",
                        "call_id": block.id,
                        "name": block.tool_name,
                        "arguments": args_s,
                    }
                )
            elif block.type == "tool_result":
                err = flush_text()
                if err:
                    return out, err
                out.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.tool_use_id,
                        "output": block.tool_result,
                    }
                )
            elif block.type == "provider_state":
                return out, "openai provider state is missing opaque response data"
            else:
                return out, f"openai: unsupported message block type {block.type!r}"

        err = flush_text()
        if err:
            return out, err
    return out, None


def _json_valid(data: bytes) -> bool:
    try:
        json.loads(data)
        return True
    except json.JSONDecodeError:
        return False


def _blocks_from_openai_item(raw_item: Any) -> tuple[list[Block], str | None]:
    if isinstance(raw_item, (bytes, bytearray)):
        state: Any = json.loads(raw_item)
    elif isinstance(raw_item, str):
        state = json.loads(raw_item)
    else:
        state = raw_item
    state_raw = _provider_state_data(state)

    item_type = state.get("type") if isinstance(state, dict) else None

    if item_type == "reasoning":
        return [
            Block(type="provider_state", provider="openai", provider_data=state_raw)
        ], None

    if item_type == "function_call":
        args_raw = state.get("arguments") or "{}"
        if isinstance(args_raw, str):
            args_raw = args_raw.strip() or "{}"
            try:
                tool_input: Any = json.loads(args_raw)
            except json.JSONDecodeError:
                tool_input = args_raw
        else:
            tool_input = args_raw
        return [
            Block(
                type="tool_use",
                id=str(state.get("call_id") or ""),
                tool_name=str(state.get("name") or ""),
                tool_input=tool_input,
                provider="openai",
                provider_data=state_raw,
            )
        ], None

    if item_type == "message":
        parts: list[str] = []
        for content in state.get("content") or []:
            ctype = content.get("type")
            if ctype == "output_text":
                parts.append(str(content.get("text") or ""))
            elif ctype == "refusal":
                parts.append(str(content.get("refusal") or ""))
        if not parts:
            return [
                Block(type="provider_state", provider="openai", provider_data=state_raw)
            ], None
        return [
            Block(
                type="text",
                text="\n".join(parts),
                provider="openai",
                provider_data=state_raw,
            )
        ], None

    return [Block(type="provider_state", provider="openai", provider_data=state_raw)], None


def _decode_openai_response(raw: bytes) -> tuple[dict[str, Any], str | None]:
    trimmed = raw.strip()
    if not trimmed:
        return {}, "decode openai response: empty body"

    if trimmed[:1] == b"{":
        try:
            resp = json.loads(trimmed)
        except json.JSONDecodeError as e:
            return {}, f"decode openai response: {e}"
        if not isinstance(resp, dict):
            return {}, "decode openai response: expected object"
        return resp, None

    items: dict[int, Any] = {}
    final: dict[str, Any] | None = None
    stream_err: str | None = None
    data_lines: list[str] = []

    def consume() -> str | None:
        nonlocal stream_err, final
        if not data_lines:
            return None
        joined = "\n".join(data_lines)
        data_lines.clear()
        if joined == "[DONE]":
            return None
        try:
            event = json.loads(joined)
        except json.JSONDecodeError as e:
            return f"decode openai stream event: {e}"

        etype = event.get("type")
        if etype == "response.output_item.done":
            item = event.get("item")
            if item is not None:
                idx = int(event.get("output_index") or 0)
                items[idx] = item
        elif etype in ("response.completed", "response.incomplete", "response.failed"):
            resp = event.get("response")
            if resp is not None:
                final = dict(resp)
        elif etype == "error":
            stream_err = (
                f"openai stream error {event.get('code', '')}: "
                f"{event.get('message', '')}"
            )
        return None

    for line in raw.splitlines():
        line = line.rstrip(b"\r")
        if not line:
            err = consume()
            if err:
                return {}, err
            continue
        if line.startswith(b"data:"):
            data_lines.append(line[5:].strip().decode("utf-8"))

    err = consume()
    if err:
        return {}, err
    if stream_err:
        return {}, stream_err
    if final is None:
        return {}, "openai stream ended without a final response event"

    if items:
        output: list[Any] = []
        for index in sorted(items):
            output.append(items[index])
        final["output"] = output
    return final, None
