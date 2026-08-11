import pytest

from meat_python_plus.providers.resolve import (
    CODEX_ONLY_MSG,
    NOUS_BASE_URL,
    TOKENHUB_BASE_URL,
    resolve_model_name,
    resolve_provider,
)


def test_resolve_model_from_env(monkeypatch):
    monkeypatch.delenv("MEAT_MODEL", raising=False)
    assert resolve_model_name("") == "gpt-5.6-sol"
    monkeypatch.setenv("MEAT_MODEL", "hy3")
    assert resolve_model_name("") == "hy3"
    assert resolve_model_name("explicit") == "explicit"


def test_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)
    monkeypatch.delenv("MEAT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    r = resolve_provider("gpt-4.1-mini")
    assert r.provider_name == "openai"
    assert r.base_url.endswith("/v1")
    assert r.api_key == "sk-test"


def test_nous_by_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)
    monkeypatch.delenv("MEAT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    r = resolve_provider("gpt-4.1-mini")
    assert r.provider_name == "nous"
    assert r.base_url == NOUS_BASE_URL


def test_nous_by_model(monkeypatch):
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ignored-for-nous-model")
    r = resolve_provider("nous/deepseek/deepseek-v4-flash")
    assert r.provider_name == "nous"
    assert r.model == "deepseek/deepseek-v4-flash"
    assert r.base_url == NOUS_BASE_URL


def test_tokenhub_hy3(monkeypatch):
    monkeypatch.setenv("TOKENHUB_API_KEY", "th-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ignored")
    r = resolve_provider("hy3")
    assert r.provider_name == "tokenhub"
    assert r.model == "hy3"
    assert r.base_url == TOKENHUB_BASE_URL


def test_tokenhub_prefix(monkeypatch):
    monkeypatch.setenv("TOKENHUB_API_KEY", "th-key")
    r = resolve_provider("tokenhub/deepseek-v4-flash")
    assert r.provider_name == "tokenhub"
    assert r.model == "deepseek-v4-flash"


def test_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    r = resolve_provider("claude-opus-4-8")
    assert r.kind == "anthropic"
    assert r.provider_name == "anthropic"
    assert r.model == "claude-opus-4-8"


def test_custom_base(monkeypatch):
    monkeypatch.setenv("MEAT_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MEAT_API_KEY", "custom-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = resolve_provider("my-model")
    assert r.provider_name == "custom"
    assert r.base_url == "https://example.com/v1"
    assert r.api_key == "custom-key"


def test_native_openai_selects_responses_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)
    monkeypatch.delenv("MEAT_BASE_URL", raising=False)
    r = resolve_provider("gpt-4.1-mini")
    assert r.kind == "openai_responses"
    assert r.provider_name == "openai"


def test_tokenhub_resolve_stays_chat_completions(monkeypatch):
    monkeypatch.setenv("TOKENHUB_API_KEY", "th-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-win-for-hy3")
    r = resolve_provider("hy3")
    assert r.kind == "openai_compat"
    assert r.provider_name == "tokenhub"
    assert r.base_url == TOKENHUB_BASE_URL


def test_nous_resolve_stays_chat_completions(monkeypatch):
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-win-for-nous-model")
    r = resolve_provider("nous/deepseek/deepseek-v4-flash")
    assert r.kind == "openai_compat"
    assert r.provider_name == "nous"
    assert r.base_url == NOUS_BASE_URL


def test_codex_only_fails(monkeypatch):
    for k in (
        "OPENAI_API_KEY",
        "NOUS_API_KEY",
        "TOKENHUB_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEAT_API_KEY",
        "MEAT_BASE_URL",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CODEX_AUTH_JSON", '{"tokens":{}}')
    with pytest.raises(ValueError, match="CODEX_AUTH_JSON"):
        resolve_provider("gpt-4.1-mini")
    assert "OPENAI_API_KEY" in CODEX_ONLY_MSG
