"""Shared pytest fixtures for CLI tests."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

import pytest

_INDEXED_PROVIDER_ENV = re.compile(
    r"^(?:LLM_PROVIDER_\d+|MERGECRAFT_CUSTOM_PROVIDER_(?:API_KEY|BASE_URL)_\d+)"
)


@pytest.fixture(autouse=True)
def _isolate_indexed_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep exported ``LLM_PROVIDER_<N>*`` keys out of env-index allocation in tests."""
    for key in list(os.environ):
        if _INDEXED_PROVIDER_ENV.match(key):
            monkeypatch.delenv(key)


@pytest.fixture(autouse=True)
def _reset_legacy_credential_warned_keys() -> Iterator[None]:
    """Isolate D7 once-per-legacy-key credential warnings between tests."""
    from mergecraft.cli import provider_cmd

    provider_cmd._LEGACY_CREDENTIAL_WARNED_KEYS.clear()
    yield
    provider_cmd._LEGACY_CREDENTIAL_WARNED_KEYS.clear()
