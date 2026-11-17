"""Generate a single bounded text reply from workflow-owned provider settings.

Module: mergecraft.agents.discuss
Depends: mergecraft.agents.chat_completion, mergecraft.config.env, mergecraft.modes.Discuss, httpx

Exports:
    Classes:
        DiscussModelError — A failed model request or invalid reply body.
    Functions:
        generate_discuss_reply — Generate a bounded text reply from one thread's context.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

import httpx

from mergecraft.agents.chat_completion import chat_completion_content, request_chat_completion
from mergecraft.config.env import ActionInputEnv, ProviderGatewayEnv
from mergecraft.errors import ConfigurationError
from mergecraft.models import resolve_model_slug
from mergecraft.modes.Discuss import SYSTEM_PROMPT

_DEFAULT_MODEL = "opencode-go/deepseek-v4.1-flash"
_GO_URL = "https://opencode.ai/inference/go/openai/v1"
_OPENAI_URL = "https://api.openai.com/v1"
_MAX_COMPLETION_TOKENS = 800
_MAX_REPLY_CHARS = 3_000


class DiscussModelError(RuntimeError):
    """The model endpoint could not provide one usable text reply."""


async def generate_discuss_reply(context: str, *, thread_key: str) -> str:
    """Send one tool-free model request, without config loading or fallback."""
    model = ActionInputEnv().model or _DEFAULT_MODEL
    provider, _, model_id = (resolve_model_slug(model) or model).partition("/")
    env = ProviderGatewayEnv()
    extra_headers = {"User-Agent": "mergeCraft-Discuss"}
    token_parameter = "max_tokens"
    base_url: str | None
    if provider == "opencode-go":
        base_url, secret = _GO_URL, env.opencode_go_api_key
        digest = hashlib.sha256(thread_key.encode()).hexdigest()
        extra_headers["x-opencode-session"] = f"ses_{digest}"
    elif provider == "openai":
        base_url, secret = _OPENAI_URL, env.openai_api_key
        token_parameter = "max_completion_tokens"
    else:
        base_url, secret = env.custom_provider_base_url, env.custom_provider_api_key

    key = secret.get_secret_value().strip() if secret else ""
    if not (model_id and base_url and key):
        msg = (
            "Discuss requires a provider/model input with OpenCode Go, OpenAI API, "
            "or both MERGECRAFT_CUSTOM_PROVIDER_BASE_URL and MERGECRAFT_CUSTOM_PROVIDER_API_KEY."
        )
        raise ConfigurationError(msg)
    url = urlsplit(base_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.query
        or url.fragment
    ):
        msg = "Discuss requires an HTTPS model endpoint without embedded credentials or query data."
        raise ConfigurationError(msg)

    payload: dict[str, Any] = {
        "model": model_id,
        token_parameter: _MAX_COMPLETION_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
    }
    response = await request_chat_completion(
        base_url=base_url,
        api_key=key,
        payload=payload,
        http_timeout_s=60.0,
        client_factory=httpx.AsyncClient,
        headers=extra_headers,
    )
    if not response.is_success:
        msg = f"Discuss model returned HTTP {response.status_code}."
        raise DiscussModelError(msg)
    try:
        reply = chat_completion_content(response.json())
    except (ValueError, RecursionError):
        reply = None
    answer = reply.strip() if reply else ""
    if not answer or len(answer) > _MAX_REPLY_CHARS:
        msg = "Discuss model did not return a bounded text reply."
        raise DiscussModelError(msg)
    return answer
