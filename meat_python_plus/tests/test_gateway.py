"""W7 contract: exe.dev managed LLM gateway (Go gateway.go)."""

from __future__ import annotations

import json

import httpx
import pytest

from _parity_helpers import import_or_fail, require_attr


@pytest.fixture
def gateway_module():
    return import_or_fail("meat_python_plus.providers.gateway")


def test_discover_exe_gateway_base(gateway_module, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "exe.dev"
    marker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(gateway_module, "EXE_DEV_MARKER_PATH", str(marker), raising=False)

    reflection_body = json.dumps(
        {"integrations": [{"name": "discord", "type": "discord"}, {"name": "llm", "type": "llm"}]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json=json.loads(reflection_body), headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(gateway_module, "REFLECTION_INTEGRATIONS_URL", "https://reflection.test", raising=False)

    discover = require_attr(gateway_module, "discover_exe_gateway_base")
    got = discover(http_client=client)
    assert got == "https://llm.int.exe.xyz"


def test_discover_exe_gateway_base_no_marker(gateway_module, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(gateway_module, "EXE_DEV_MARKER_PATH", str(missing), raising=False)
    discover = require_attr(gateway_module, "discover_exe_gateway_base")
    assert discover() == ""


def test_discover_exe_gateway_base_no_llm_integration(
    gateway_module, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "exe.dev"
    marker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(gateway_module, "EXE_DEV_MARKER_PATH", str(marker), raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={"integrations": [{"name": "discord", "type": "discord"}]},
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(gateway_module, "REFLECTION_INTEGRATIONS_URL", "https://reflection.test", raising=False)
    discover = require_attr(gateway_module, "discover_exe_gateway_base")
    assert discover(http_client=client) == ""


def test_discover_exe_gateway_base_team(gateway_module, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "exe.dev"
    marker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(gateway_module, "EXE_DEV_MARKER_PATH", str(marker), raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={"integrations": [{"name": "acme", "type": "llm", "team": True}]},
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(gateway_module, "REFLECTION_INTEGRATIONS_URL", "https://reflection.test", raising=False)
    discover = require_attr(gateway_module, "discover_exe_gateway_base")
    assert discover(http_client=client) == "https://acme.team.exe.xyz"


def test_resolve_openai_prefers_explicit_key_over_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve_mod = import_or_fail("meat_python_plus.providers.resolve")
    gateway_mod = import_or_fail("meat_python_plus.providers.gateway")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-explicit")
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.setattr(gateway_mod, "discover_exe_gateway_base", lambda **_: "https://llm.int.exe.xyz", raising=False)
    resolved = resolve_mod.resolve_provider("")
    assert resolved.api_key == "sk-explicit"
    assert resolved.kind == "openai_responses"


def test_resolve_openai_falls_back_to_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve_mod = import_or_fail("meat_python_plus.providers.resolve")
    gateway_mod = import_or_fail("meat_python_plus.providers.gateway")
    for key in (
        "OPENAI_API_KEY",
        "NOUS_API_KEY",
        "TOKENHUB_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEAT_API_KEY",
        "MEAT_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        gateway_mod,
        "discover_exe_gateway_base",
        lambda **_: "https://llm.int.exe.xyz",
        raising=False,
    )
    implicit = require_attr(gateway_mod, "IMPLICIT_GATEWAY_KEY")
    resolved = resolve_mod.resolve_provider("")
    assert resolved.api_key == implicit
    assert resolved.base_url.endswith("/openai")
