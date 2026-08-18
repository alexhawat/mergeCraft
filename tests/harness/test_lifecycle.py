"""RH2 — pytest lifecycle and provider env patching."""

from __future__ import annotations

import os

import httpx
import pytest

from mergecraft.agents.openai_compatible_gateways import ProviderConfig
from mergecraft.agents.opencode import build_custom_provider
from mergecraft.cli.auth_cmd import _validate_openai_compatible_key
from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.pytest_plugin import load_harness_fixtures
from tests.support.provider_harness.server import ProviderHarnessServer


def test_provider_can_use_local_openai_compatible_base_url(provider_harness, monkeypatch) -> None:
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", provider_harness.base_url)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", DUMMY_API_KEY)
    emitted = build_custom_provider("default/dummy")
    assert emitted is not None
    assert emitted["default"]["options"]["baseURL"] == provider_harness.base_url


def test_auth_models_probe_succeeds_against_stub(provider_harness) -> None:
    assert _validate_openai_compatible_key(
        api_key=DUMMY_API_KEY,
        base_url=provider_harness.base_url,
        label="harness",
    )


def test_fixture_state_is_isolated_between_tests(provider_harness) -> None:
    provider_harness.reload(load_harness_fixtures("no-findings"))
    assert (
        httpx.post(
            provider_harness.base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
            json={"model": "default/dummy", "messages": []},
            timeout=5.0,
        ).status_code
        == 200
    )
    provider_harness.reload(load_harness_fixtures("no-findings"))
    assert (
        httpx.post(
            provider_harness.base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
            json={"model": "default/dummy", "messages": []},
            timeout=5.0,
        ).status_code
        == 200
    )


def test_server_stops_during_fixture_teardown() -> None:
    server = ProviderHarnessServer()
    server.start()
    url = server.url_for("/health")
    assert httpx.get(url, timeout=5.0).status_code == 200
    server.close()
    with pytest.raises((httpx.ConnectError, httpx.ReadError, OSError)):
        httpx.get(url, timeout=1.0)


def test_client_is_constructed_after_environment_patch(provider_harness) -> None:
    assert os.environ["MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"] == provider_harness.base_url
    assert os.environ["MERGECRAFT_CUSTOM_PROVIDER_API_KEY"] == DUMMY_API_KEY


def test_localhost_base_url_is_already_legal() -> None:
    cfg = ProviderConfig(
        provider_id="default",
        base_url="http://127.0.0.1:9/v1",
        api_key_env="MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    )
    assert cfg.base_url.endswith("/v1")
