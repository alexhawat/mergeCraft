"""Named deterministic failure profiles for the provider harness."""

from __future__ import annotations

from dataclasses import dataclass

from tests.support.provider_harness.schema import ProfileName


@dataclass(frozen=True)
class ProfileOutcome:
    status_code: int
    headers: dict[str, str]
    body: object | None = None
    raw_body: bytes | None = None
    timeout_hold_ms: int = 0
    disconnect_after_chunk: int | None = None


def apply_profile(name: ProfileName | None) -> ProfileOutcome | None:
    if name is None:
        return None
    if name == "http_429":
        return ProfileOutcome(
            status_code=429,
            headers={"Retry-After": "1", "x-ratelimit-remaining": "0"},
            body={"error": "rate_limit"},
        )
    if name == "http_500":
        return ProfileOutcome(status_code=500, headers={}, body={"error": "internal"})
    if name == "http_401":
        return ProfileOutcome(status_code=401, headers={}, body={"error": "unauthorized"})
    if name == "timeout":
        return ProfileOutcome(status_code=200, headers={}, body=None, timeout_hold_ms=5000)
    if name == "malformed_json":
        return ProfileOutcome(status_code=200, headers={}, raw_body=b"{not-json")
    if name == "empty_stream":
        return ProfileOutcome(
            status_code=200, headers={"Content-Type": "text/event-stream"}, body=""
        )
    if name == "disconnect_after_chunk":
        return ProfileOutcome(
            status_code=200,
            headers={"Content-Type": "text/event-stream"},
            disconnect_after_chunk=1,
        )
    msg = f"unknown profile {name!r}"
    raise ValueError(msg)
