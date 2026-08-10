"""Resolve which HTTP backend and credentials to use from env + model id."""

from __future__ import annotations

import os
from dataclasses import dataclass

from meat_python_plus.model import Model
from meat_python_plus.providers.anthropic_msgs import AnthropicMessagesModel
from meat_python_plus.providers.openai_compat import OpenAICompatModel

DEFAULT_MODEL = "gpt-4.1-mini"

NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"

CODEX_ONLY_MSG = (
    "CODEX_AUTH_JSON is a Codex CLI subscription credential, not a Chat Completions "
    "API key. meat_python_plus needs an HTTP chat API. Set OPENAI_API_KEY, "
    "NOUS_API_KEY, TOKENHUB_API_KEY, ANTHROPIC_API_KEY, or MEAT_BASE_URL+MEAT_API_KEY "
    "(or OPENAI_BASE_URL)."
)


@dataclass(frozen=True)
class ResolvedProvider:
    kind: str  # openai_compat | anthropic
    model: str
    api_key: str
    base_url: str
    provider_name: str  # openai | nous | tokenhub | custom | anthropic


def resolve_model_name(model: str = "") -> str:
    if model:
        return model
    return os.environ.get("MEAT_MODEL") or DEFAULT_MODEL


def is_anthropic_model(model: str) -> bool:
    m = model.removeprefix("anthropic/")
    return m.startswith("claude-")


def is_nous_model(model: str) -> bool:
    lower = model.lower()
    return (
        lower.startswith("nous/")
        or lower.startswith("deepseek/")
        or "deepseek-v4" in lower
    )


def is_tokenhub_model(model: str) -> bool:
    lower = model.lower()
    if lower.startswith("tokenhub/"):
        return True
    if lower in {"hy3", "tokenhub/hy3"}:
        return True
    if lower.startswith("hy3"):
        return True
    return False


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def resolve_provider(model: str = "") -> ResolvedProvider:
    """Pick provider from model id hints and available env credentials.

    Priority when model does not force a vendor:
      1. MEAT_BASE_URL + (MEAT_API_KEY|OPENAI_API_KEY)
      2. OPENAI_API_KEY
      3. NOUS_API_KEY
      4. TOKENHUB_API_KEY
      5. ANTHROPIC_API_KEY (only for Claude model ids)
    Model-id prefixes (claude-, nous/, tokenhub/, hy3, deepseek/) force that vendor.
    """
    model = resolve_model_name(model)
    openai_key = _env("OPENAI_API_KEY")
    nous_key = _env("NOUS_API_KEY")
    tokenhub_key = _env("TOKENHUB_API_KEY")
    anthropic_key = _env("ANTHROPIC_API_KEY")
    meat_base = (_env("MEAT_BASE_URL") or _env("OPENAI_BASE_URL")).rstrip("/")
    meat_key = _env("MEAT_API_KEY")

    if is_anthropic_model(model):
        if not anthropic_key and not _env("ANTHROPIC_BASE_URL"):
            raise ValueError(
                "no Anthropic credentials: set ANTHROPIC_API_KEY "
                "(Claude models require the Messages API)"
            )
        base = (_env("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        return ResolvedProvider(
            kind="anthropic",
            model=model.removeprefix("anthropic/"),
            api_key=anthropic_key,
            base_url=base,
            provider_name="anthropic",
        )

    if is_tokenhub_model(model):
        if not tokenhub_key:
            raise ValueError(
                f"TokenHub model {model!r} requires TOKENHUB_API_KEY "
                f"(base {TOKENHUB_BASE_URL})"
            )
        return ResolvedProvider(
            kind="openai_compat",
            model=model.removeprefix("tokenhub/"),
            api_key=tokenhub_key,
            base_url=TOKENHUB_BASE_URL,
            provider_name="tokenhub",
        )

    if is_nous_model(model):
        if not nous_key:
            raise ValueError(
                f"Nous/DeepSeek model {model!r} requires NOUS_API_KEY "
                f"(base {NOUS_BASE_URL})"
            )
        clean = model[5:] if model.lower().startswith("nous/") else model
        return ResolvedProvider(
            kind="openai_compat",
            model=clean,
            api_key=nous_key,
            base_url=NOUS_BASE_URL,
            provider_name="nous",
        )

    # Custom OpenAI-compatible (explicit base URL).
    if meat_base and (meat_key or openai_key):
        return ResolvedProvider(
            kind="openai_compat",
            model=model,
            api_key=meat_key or openai_key,
            base_url=meat_base,
            provider_name="custom",
        )

    if openai_key:
        base = meat_base or "https://api.openai.com/v1"
        return ResolvedProvider(
            kind="openai_compat",
            model=model,
            api_key=openai_key,
            base_url=base,
            provider_name="openai",
        )

    if nous_key:
        return ResolvedProvider(
            kind="openai_compat",
            model=model,
            api_key=nous_key,
            base_url=NOUS_BASE_URL,
            provider_name="nous",
        )

    if tokenhub_key:
        return ResolvedProvider(
            kind="openai_compat",
            model=model,
            api_key=tokenhub_key,
            base_url=TOKENHUB_BASE_URL,
            provider_name="tokenhub",
        )

    if _env("CODEX_AUTH_JSON") and not any(
        [_env("OPENAI_API_KEY"), nous_key, tokenhub_key, anthropic_key, meat_key]
    ):
        raise ValueError(CODEX_ONLY_MSG)

    raise ValueError(
        "no LLM credentials: set OPENAI_API_KEY, NOUS_API_KEY, TOKENHUB_API_KEY, "
        "ANTHROPIC_API_KEY, or MEAT_BASE_URL+MEAT_API_KEY"
    )


def new_model_from_env(model: str = "") -> Model:
    resolved = resolve_provider(model)
    if resolved.kind == "anthropic":
        return AnthropicMessagesModel(
            api_key=resolved.api_key,
            model=resolved.model,
            base_url=resolved.base_url,
        )
    return OpenAICompatModel(
        api_key=resolved.api_key,
        model=resolved.model,
        base_url=resolved.base_url,
        provider_name=resolved.provider_name,
    )
