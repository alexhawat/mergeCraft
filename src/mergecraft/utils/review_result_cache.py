"""Local review-result cache, distinct from the ``mergecraft cache`` CLI typer (#378)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import ScopeReduction, resolve_run_bounds
from mergecraft.utils.run_cache import RunCache, default_cache_root, open_run_cache
from mergecraft.utils.workspace import git_repo_root

_KEY_PREFIX = "review-result:"


def review_cache_repo_identity(*, cwd: Path | str | None = None) -> str:
    """Return a stable identity for the repository or worktree being reviewed."""
    start = Path(cwd) if cwd is not None else Path.cwd()
    root = git_repo_root(str(start))
    if root is not None:
        return str(root)
    return str(start)


def review_result_cache_key(
    diff_bytes: bytes,
    *,
    model: str | None = None,
    trust_tier: str | None = None,
    prompt_extra: str | None = None,
    json_mode: bool = False,
    base_ref: str | None = None,
    repo_identity: str | None = None,
    cwd: Path | str | None = None,
) -> str:
    """Return a cache key for a materialized review, including inputs that change it."""
    identity = repo_identity if repo_identity is not None else review_cache_repo_identity(cwd=cwd)
    hasher = hashlib.sha256()
    hasher.update(diff_bytes)
    hasher.update(b"\0model=")
    hasher.update((model or "").encode("utf-8"))
    hasher.update(b"\0trust=")
    hasher.update((trust_tier or "").encode("utf-8"))
    hasher.update(b"\0prompt=")
    hasher.update((prompt_extra or "").encode("utf-8"))
    hasher.update(b"\0json=")
    hasher.update(b"1" if json_mode else b"0")
    hasher.update(b"\0base=")
    hasher.update((base_ref or "").encode("utf-8"))
    hasher.update(b"\0repo=")
    hasher.update(identity.encode("utf-8"))
    return f"{_KEY_PREFIX}{hasher.hexdigest()}"


def _open_result_cache() -> RunCache:
    bounds = resolve_run_bounds()
    return open_run_cache(root=default_cache_root(), max_bytes=bounds.cache_max_bytes)


def _scope_reduction_payload(reduction: ScopeReduction | None) -> dict[str, object] | None:
    if reduction is None:
        return None
    return {
        "original_lines": reduction.original_lines,
        "kept_lines": reduction.kept_lines,
        "omitted_paths": list(reduction.omitted_paths),
        "reason": reduction.reason,
    }


def _load_scope_reduction(raw: object) -> ScopeReduction | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("scope_reduction must be an object")
    original_lines = raw.get("original_lines")
    kept_lines = raw.get("kept_lines")
    omitted_paths = raw.get("omitted_paths")
    reason = raw.get("reason")
    if (
        not isinstance(original_lines, int)
        or not isinstance(kept_lines, int)
        or not isinstance(reason, str)
        or not isinstance(omitted_paths, list)
        or any(not isinstance(path, str) for path in omitted_paths)
    ):
        raise ValueError("scope_reduction fields are invalid")
    return ScopeReduction(
        original_lines=original_lines,
        kept_lines=kept_lines,
        omitted_paths=list(omitted_paths),
        reason=reason,
    )


def load_review_result(key: str) -> OfflineReviewResult | None:
    """Load a previously cached review result, or ``None`` on miss/corrupt."""
    cache = _open_result_cache()
    raw = cache.get(key)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    outcome_raw = payload.get("outcome")
    outcome: RunOutcome | None
    if outcome_raw is None:
        outcome = None
    elif isinstance(outcome_raw, str):
        try:
            outcome = RunOutcome(outcome_raw)
        except ValueError:
            return None
    else:
        return None
    try:
        scope_reduction = _load_scope_reduction(payload.get("scope_reduction"))
    except ValueError:
        return None
    return OfflineReviewResult(
        success=bool(payload.get("success")),
        output=payload.get("output") if isinstance(payload.get("output"), str) else None,
        error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        diff_path=payload.get("diff_path") if isinstance(payload.get("diff_path"), str) else None,
        empty_diff=bool(payload.get("empty_diff")),
        structured_output=(
            payload.get("structured_output")
            if isinstance(payload.get("structured_output"), str)
            else None
        ),
        evidence_packet_path=(
            payload.get("evidence_packet_path")
            if isinstance(payload.get("evidence_packet_path"), str)
            else None
        ),
        outcome=outcome,
        scope_reduction=scope_reduction,
    )


def store_review_result(key: str, result: OfflineReviewResult) -> None:
    """Persist a successful post-finalize review result for ``--use-cache`` / ``--resume``."""
    payload = {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "diff_path": result.diff_path,
        "empty_diff": result.empty_diff,
        "structured_output": result.structured_output,
        "evidence_packet_path": result.evidence_packet_path,
        "outcome": result.outcome.value if result.outcome is not None else None,
        "scope_reduction": _scope_reduction_payload(result.scope_reduction),
    }
    cache = _open_result_cache()
    cache.put(key, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def cache_key_for_diff_path(
    path: Path,
    *,
    model: str | None = None,
    trust_tier: str | None = None,
    prompt_extra: str | None = None,
    json_mode: bool = False,
    base_ref: str | None = None,
    repo_identity: str | None = None,
    cwd: Path | str | None = None,
) -> str:
    """Hash an on-disk unified diff plus review-changing inputs into a result-cache key."""
    return review_result_cache_key(
        path.read_bytes(),
        model=model,
        trust_tier=trust_tier,
        prompt_extra=prompt_extra,
        json_mode=json_mode,
        base_ref=base_ref,
        repo_identity=repo_identity,
        cwd=cwd,
    )


__all__ = [
    "cache_key_for_diff_path",
    "load_review_result",
    "review_cache_repo_identity",
    "review_result_cache_key",
    "store_review_result",
]
