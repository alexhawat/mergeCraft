"""Shared pytest fixtures for CLI tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_legacy_credential_warned_keys() -> Iterator[None]:
    """Isolate D7 once-per-legacy-key credential warnings between tests."""
    from mergecraft.cli import provider_cmd

    provider_cmd._LEGACY_CREDENTIAL_WARNED_KEYS.clear()
    yield
    provider_cmd._LEGACY_CREDENTIAL_WARNED_KEYS.clear()
