"""RH2 — local OpenAI-compatible stub HTTP surface."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.pytest_plugin import load_harness_fixtures
from tests.support.provider_harness.schema import load_fixture_file

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_health_and_readiness_report_server_state(provider_harness) -> None:
    assert httpx.get(provider_harness.url_for("/health"), timeout=5.0).status_code == 200
    assert httpx.get(provider_harness.url_for("/ready"), timeout=5.0).json()["status"] == "ok"


def test_non_streaming_chat_completions_returns_fixture_response(provider_harness) -> None:
    provider_harness.reload(load_harness_fixtures("no-findings"))
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": [{"role": "user", "content": "review"}]},
        timeout=5.0,
    )
    assert response.status_code == 200
    assert "No findings" in response.json()["choices"][0]["message"]["content"]


def test_models_list_accepts_dummy_key(provider_harness) -> None:
    response = httpx.get(
        provider_harness.base_url + "/models",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        timeout=5.0,
    )
    assert response.status_code == 200


def test_unknown_request_returns_strict_fixture_error(provider_harness) -> None:
    provider_harness.reload([])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "fixture_mismatch"


def test_dummy_api_key_is_accepted_only_by_test_server(provider_harness) -> None:
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": "Bearer sk-wrong"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 401
    assert "sk-mergecraft-test" not in (_REPO_ROOT / "src/mergecraft/agents/opencode.py").read_text(
        encoding="utf-8"
    )


def test_request_history_is_recorded_redacted_and_bounded(provider_harness) -> None:
    provider_harness.reload(load_harness_fixtures("no-findings"))
    httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": [{"role": "user", "content": "x"}]},
        timeout=5.0,
    )
    history = provider_harness.history
    assert 1 <= len(history) <= 32
    blob = json.dumps([entry.__dict__ for entry in history])
    assert DUMMY_API_KEY not in blob


def test_committed_fixtures_exist() -> None:
    load_fixture_file(_FIXTURES_DIR / "no-findings.json")
    load_fixture_file(_FIXTURES_DIR / "blocking-correctness.json")
