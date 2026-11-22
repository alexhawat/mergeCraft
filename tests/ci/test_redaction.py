"""CI log redaction boundary — canary must never escape (K8 / D8)."""

from __future__ import annotations

from tests.ci.support import CANARY_SECRET, load_fixture


def _paths_from_normalized(normalized: dict[str, object], redact: object) -> list[str]:
    return [
        str(normalized.get("log_excerpt", "")),
        redact.redact_for_fingerprint(str(normalized.get("log_excerpt", "")), tool_id="ci"),
        redact.cache_key_fragment(str(normalized.get("failure_fingerprint", "")), tool_id="ci"),
    ]


def test_canary_never_in_normalized_excerpt_or_fingerprint_input() -> None:
    import mergecraft.analyzers.redact as redact
    import mergecraft.ci.normalize as normalize

    fixture = load_fixture("canary_in_ci_log.json")
    normalized = normalize.normalize_failure(fixture)
    for material in _paths_from_normalized(normalized, redact):
        assert CANARY_SECRET not in material


def test_canary_never_in_artifact_paths() -> None:
    import mergecraft.ci.normalize as normalize

    fixture = load_fixture("canary_in_ci_log.json")
    fixture = dict(fixture)
    fixture["artifacts"] = [f"/tmp/run/logs/{CANARY_SECRET}.txt"]
    normalized = normalize.normalize_failure(fixture)
    joined = "\n".join(str(path) for path in normalized.get("artifacts", []))
    assert CANARY_SECRET not in joined


def test_canary_never_in_review_comment_body() -> None:
    import mergecraft.ci.normalize as normalize
    import mergecraft.ci.review as review_ci

    fixture = load_fixture("canary_in_ci_log.json")
    normalized = normalize.normalize_failure(fixture)
    body = review_ci.render_ci_failure_comment([normalized])
    assert CANARY_SECRET not in body


def test_canary_never_in_normalized_command_or_cluster_message() -> None:
    import mergecraft.ci.cluster as cluster
    import mergecraft.ci.normalize as normalize
    import mergecraft.ci.review as review_ci

    fixture = load_fixture("canary_in_ci_log.json")
    fixture = dict(fixture)
    fixture["command"] = f"pytest tests/foo --token={CANARY_SECRET}"
    normalized = normalize.normalize_failure(fixture)
    assert CANARY_SECRET not in normalized["command"]
    finding = cluster.failure_to_finding(normalized)
    assert CANARY_SECRET not in finding.message
    reports, _, _ = review_ci.analyze_ci_failures([fixture])
    assert CANARY_SECRET not in reports[0].finding.message
