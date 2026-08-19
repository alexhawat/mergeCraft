"""In-process counters for provider-harness diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HarnessMetrics:
    matches: int = 0
    mismatches: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)
    retries: int = 0
    disconnects: int = 0
    fixture_usage: dict[str, int] = field(default_factory=dict)
    total_latency_ms: float = 0.0
    request_count: int = 0

    def record_match(self, fixture_name: str, *, latency_ms: float, status_code: int) -> None:
        self.matches += 1
        self.request_count += 1
        self.fixture_usage[fixture_name] = self.fixture_usage.get(fixture_name, 0) + 1
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
        self.total_latency_ms += latency_ms

    def record_mismatch(self, *, latency_ms: float, status_code: int) -> None:
        self.mismatches += 1
        self.request_count += 1
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
        self.total_latency_ms += latency_ms

    def record_disconnect(self) -> None:
        self.disconnects += 1

    def record_retry(self) -> None:
        self.retries += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "matches": self.matches,
            "mismatches": self.mismatches,
            "status_codes": dict(self.status_codes),
            "retries": self.retries,
            "disconnects": self.disconnects,
            "fixture_usage": dict(self.fixture_usage),
            "latency_ms": self.total_latency_ms,
            "request_count": self.request_count,
        }

    def reset(self) -> None:
        self.matches = 0
        self.mismatches = 0
        self.status_codes.clear()
        self.retries = 0
        self.disconnects = 0
        self.fixture_usage.clear()
        self.total_latency_ms = 0.0
        self.request_count = 0
