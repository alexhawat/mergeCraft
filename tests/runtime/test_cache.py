"""CC3 — run cache ceiling, eviction, and concurrency (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC3.1** (RED). Implementation: **CC3.2**.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

from mergecraft.utils.run_cache import RunCache


def test_cache_has_a_size_ceiling_and_eviction(tmp_path: Path) -> None:
    """Cache enforces a byte ceiling and evicts oldest entries."""
    cache = RunCache(root=tmp_path / "cache", max_bytes=200)
    cache.put("alpha", b"x" * 120)
    cache.put("beta", b"y" * 120)
    assert cache.total_bytes() <= 200
    assert cache.get("beta") == b"y" * 120
    assert cache.get("alpha") is None or cache.total_bytes() <= 200


def test_concurrent_cli_runs_do_not_corrupt_the_cache(tmp_path: Path) -> None:
    """Two concurrent writers over one cache dir both complete without corruption."""
    cache_root = tmp_path / "shared-cache"
    errors: list[str] = []

    def _worker(worker_id: int) -> int:
        cache = RunCache(root=cache_root, max_bytes=4096)
        key = f"worker-{worker_id}"
        payload = f"payload-{worker_id}".encode()
        cache.put(key, payload)
        read_back = cache.get(key)
        if read_back != payload:
            errors.append(f"{key}: expected {payload!r}, got {read_back!r}")
        return worker_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_worker, (1, 2)))

    assert results == [1, 2]
    assert not errors, "; ".join(errors)
