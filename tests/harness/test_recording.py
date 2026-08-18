"""RH5 — sanitized recording workflow."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.pytest_plugin import load_harness_fixtures
from tests.support.provider_harness.recorder import write_record


def test_sanitized_record_can_be_replayed(provider_harness, monkeypatch, tmp_path, chdir_tmp):
    monkeypatch.setenv("MERGECRAFT_PROVIDER_HARNESS_RECORD", "1")
    provider_harness.reload(load_harness_fixtures("no-findings"))
    httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    records = list(Path(".ignorelocal/provider-harness/records").glob("*.json"))
    assert records
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    assert DUMMY_API_KEY not in json.dumps(payload)


def test_recording_preserves_match_fields_and_response_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_PROVIDER_HARNESS_RECORD", "1")
    fixture = load_harness_fixtures("no-findings")[0]
    path = write_record(
        request={"provider": "default", "model": "dummy", "body": {}}, fixture=fixture
    )
    assert path is not None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["match"]["provider"] == "default"
    assert data["response"]


def test_recorder_writes_under_ignorelocal_not_committed_fixtures(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_PROVIDER_HARNESS_RECORD", "1")
    fixture = load_harness_fixtures("no-findings")[0]
    path = write_record(
        request={"provider": "default", "model": "dummy", "body": {}}, fixture=fixture
    )
    assert path is not None
    assert str(path).startswith(str(tmp_path / ".ignorelocal"))


@pytest.fixture
def chdir_tmp(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
