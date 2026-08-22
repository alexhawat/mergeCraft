from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def fetch(url: str) -> str:
    return url
