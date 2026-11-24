"""Positive fixture: constant sleep allowed via inline suppression."""

from __future__ import annotations

import time


def test_polling_backoff() -> None:
    time.sleep(0.01)  # honesty: allow bounded spin until subprocess exits
    assert True