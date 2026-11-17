"""Tool-free HTTP transport shared by Lite review and Discuss.

Module: mergecraft.agents.chat_completion
Depends: httpx

Exports:
    Functions:
        request_chat_completion — Send a single Chat Completions HTTP request.
        chat_completion_content — Extract the first text choice from a completion response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx


async def request_chat_completion(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    http_timeout_s: float,
    client_factory: Callable[..., httpx.AsyncClient],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Send one Chat Completions request through the supplied HTTP client."""
    async with client_factory(timeout=http_timeout_s) as client:
        return await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={**(headers or {}), "Authorization": f"Bearer {api_key}"},
        )


def chat_completion_content(body: Any) -> str | None:
    """Extract text from the first completion choice, if present."""
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None
