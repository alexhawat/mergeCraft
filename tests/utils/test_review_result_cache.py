"""Pin review-result cache keys and corrupt-load behaviour (Thermos / #378)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.review_result_cache import (
    cache_key_for_diff_path,
    load_review_result,
    review_result_cache_key,
    store_review_result,
)
from mergecraft.utils.run_cache import RunCache, open_run_cache

_DIFF = b"diff --git a/x.py b/x.py\n+print(1)\n"


def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "run-cache"
    monkeypatch.setenv("MERGECRAFT_CACHE_DIR", str(root))
    return root


@pytest.mark.parametrize(
    ("field", "value_a", "value_b"),
    [
        ("trust_tier", "trusted", "untrusted"),
        ("prompt_extra", "--focus security", "--focus tests"),
        ("json_mode", False, True),
        ("base_ref", "main", "HEAD"),
    ],
)
def test_review_result_cache_key_differs_when_inputs_change(
    field: str, value_a: object, value_b: object
) -> None:
    """Unit: same diff bytes + model, different trust/prompt/json/base → different key."""
    base = {
        "model": "claude-opus",
        "trust_tier": "trusted",
        "prompt_extra": None,
        "json_mode": False,
        "base_ref": "main",
    }
    key_a = review_result_cache_key(_DIFF, **{**base, field: value_a})
    key_b = review_result_cache_key(_DIFF, **{**base, field: value_b})
    assert key_a != key_b
    assert key_a.startswith("review-result:")
    assert key_b.startswith("review-result:")


@pytest.mark.parametrize(
    ("field", "value_a", "value_b"),
    [
        ("trust_tier", "trusted", "untrusted"),
        ("prompt_extra", "alpha", "beta"),
        ("json_mode", False, True),
        ("base_ref", "origin/main", "HEAD~1"),
    ],
)
def test_cache_key_for_diff_path_differs_when_inputs_change(
    tmp_path: Path, field: str, value_a: object, value_b: object
) -> None:
    """Unit: on-disk helper hashes the same bytes through the same key dimensions."""
    path = tmp_path / "change.diff"
    path.write_bytes(_DIFF)
    base = {
        "model": "claude-opus",
        "trust_tier": "trusted",
        "prompt_extra": None,
        "json_mode": False,
        "base_ref": "main",
    }
    key_a = cache_key_for_diff_path(path, **{**base, field: value_a})
    key_b = cache_key_for_diff_path(path, **{**base, field: value_b})
    assert key_a != key_b
    assert key_a == review_result_cache_key(_DIFF, **{**base, field: value_a})


def test_review_result_cache_key_empty_model_differs_from_resolved_slug() -> None:
    """Unit: callers must hash the resolved slug; empty ``model`` is not ``opus``."""
    empty = review_result_cache_key(_DIFF, model=None)
    resolved = review_result_cache_key(_DIFF, model="claude-opus")
    other = review_result_cache_key(_DIFF, model="claude-sonnet")
    assert empty != resolved
    assert resolved != other


def test_load_review_result_returns_none_for_corrupt_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: corrupt JSON is a cache miss, not a decode crash."""
    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m")
    cache = open_run_cache(root=tmp_path / "run-cache", max_bytes=1_000_000)
    cache.put(key, b"{not-json")
    assert load_review_result(key) is None


def test_load_review_result_returns_none_for_non_utf8_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: non-UTF8 bytes are a miss, not UnicodeDecodeError."""
    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m")
    cache = RunCache(root=tmp_path / "run-cache", max_bytes=1_000_000)
    cache.put(key, b"\xff\xfe not utf-8")
    assert load_review_result(key) is None


def test_load_review_result_returns_none_for_non_enum_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: ``outcome='not-an-outcome'`` is a miss and must not raise ValueError."""
    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m")
    payload = {
        "success": True,
        "output": "ok",
        "error": None,
        "diff_path": "x.diff",
        "empty_diff": False,
        "structured_output": '{"findings":[]}',
        "evidence_packet_path": None,
        "outcome": "not-an-outcome",
    }
    cache = open_run_cache(root=tmp_path / "run-cache", max_bytes=1_000_000)
    cache.put(key, json.dumps(payload).encode("utf-8"))
    loaded = load_review_result(key)
    assert loaded is None


def test_store_then_load_round_trip_includes_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: a successful store persists ``structured_output`` for cache hits."""
    from mergecraft.review.offline_result import OfflineReviewResult

    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m", json_mode=True)
    stored = OfflineReviewResult(
        success=True,
        output="review body",
        structured_output='{"findings":[]}',
        diff_path="x.diff",
        outcome=RunOutcome.passed,
    )
    store_review_result(key, stored)
    loaded = load_review_result(key)
    assert loaded is not None
    assert loaded.success is True
    assert loaded.structured_output == '{"findings":[]}'
    assert loaded.outcome is RunOutcome.passed
    assert loaded.scope_reduction is None


def test_store_then_load_round_trip_persists_scope_reduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: cached results keep ``ScopeReduction`` fields."""
    from mergecraft.review.offline_result import OfflineReviewResult
    from mergecraft.utils.run_bounds import ScopeReduction

    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m")
    reduction = ScopeReduction(
        original_lines=400,
        kept_lines=120,
        omitted_paths=["vendor/huge.py"],
        reason="max_diff_lines",
    )
    stored = OfflineReviewResult(
        success=True,
        output="review body",
        structured_output='{"findings":[]}',
        diff_path="x.diff",
        outcome=RunOutcome.passed,
        scope_reduction=reduction,
    )
    store_review_result(key, stored)
    loaded = load_review_result(key)
    assert loaded is not None
    assert loaded.scope_reduction is not None
    assert loaded.scope_reduction.original_lines == 400
    assert loaded.scope_reduction.kept_lines == 120
    assert loaded.scope_reduction.omitted_paths == ["vendor/huge.py"]
    assert loaded.scope_reduction.reason == "max_diff_lines"


@pytest.mark.parametrize(
    "scope_reduction",
    [
        "not-an-object",
        {"original_lines": "400", "kept_lines": 1, "omitted_paths": [], "reason": "x"},
        {"original_lines": 1, "kept_lines": 1, "omitted_paths": [1], "reason": "x"},
        {"original_lines": 1, "kept_lines": 1, "omitted_paths": [], "reason": None},
    ],
)
def test_invalid_scope_reduction_is_a_cache_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_reduction: object,
) -> None:
    """Error: corrupt ``scope_reduction`` JSON is a miss, not a crash."""
    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m")
    payload = {
        "success": True,
        "output": "ok",
        "error": None,
        "diff_path": "x.diff",
        "empty_diff": False,
        "structured_output": None,
        "evidence_packet_path": None,
        "outcome": "passed",
        "scope_reduction": scope_reduction,
    }
    cache = open_run_cache(root=tmp_path / "run-cache", max_bytes=1_000_000)
    cache.put(key, json.dumps(payload).encode("utf-8"))
    assert load_review_result(key) is None


def test_legacy_payload_without_scope_reduction_loads_other_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge: missing ``scope_reduction`` key does not drop other cached fields."""
    _isolate_cache(tmp_path, monkeypatch)
    key = review_result_cache_key(_DIFF, model="m")
    payload = {
        "success": True,
        "output": "legacy review",
        "error": None,
        "diff_path": "legacy.diff",
        "empty_diff": False,
        "structured_output": '{"findings":[]}',
        "evidence_packet_path": "/tmp/legacy-packet.json",
        "outcome": "passed",
    }
    cache = open_run_cache(root=tmp_path / "run-cache", max_bytes=1_000_000)
    cache.put(key, json.dumps(payload).encode("utf-8"))
    loaded = load_review_result(key)
    assert loaded is not None
    assert loaded.output == "legacy review"
    assert loaded.diff_path == "legacy.diff"
    assert loaded.structured_output == '{"findings":[]}'
    assert loaded.evidence_packet_path == "/tmp/legacy-packet.json"
    assert loaded.outcome is RunOutcome.passed
    assert loaded.scope_reduction is None
