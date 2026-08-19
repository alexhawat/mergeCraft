"""Pytest integration for the provider-harness HTTP stub."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.schema import FixtureSpec, load_fixture_file
from tests.support.provider_harness.server import ProviderHarnessServer

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "harness" / "fixtures"


@pytest.fixture
def provider_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProviderHarnessServer]:
    server = ProviderHarnessServer()
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", DUMMY_API_KEY)
    server.start()
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", server.base_url)
    yield server
    server.close()


def load_harness_fixtures(*names: str) -> list[FixtureSpec]:
    return [load_fixture_file(_FIXTURES_DIR / f"{name}.json") for name in names]
