"""CI log redaction boundary — canary must never escape (K8 / D8)."""

from __future__ import annotations

import pytest

from tests.analyzers.support import import_module as import_analyzer_module
from tests.ci.support import CANARY_SECRET, import_module, load_fixture


def _paths_from_normalized(normalized: dict[str, object], redact: object) -> list[str]:
    return [
        str(normalized.get("log_excerpt", "")),
        redact.redact_for_fingerprint(str(normalized.get("log_excerpt", "")), tool_id="ci"),
        redact.cache_key_fragment(str(normalized.get("failure_fingerprint", "")), tool_id="ci"),
    ]


@pytest.mark.xfail(reason="green after K1: CI ingest redaction at normalization", strict=False)
def test_canary_never_in_normalized_excerpt_or_fingerprint_input() -> None:
    normalize = import_module("mergecraft.ci.normalize")
    redact = import_analyzer_module("mergecraft.analyzers.redact")
    fixture = load_fixture("canary_in_ci_log.json")
    normalized = normalize.normalize_failure(fixture)
    for material in _paths_from_normalized(normalized, redact):
        assert CANARY_SECRET not in material


@pytest.mark.xfail(reason="green after K1: artifact paths redacted at ingest", strict=False)
def test_canary_never_in_artifact_paths() -> None:
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("canary_in_ci_log.json")
    fixture = dict(fixture)
    fixture["artifacts"] = [f"/tmp/run/logs/{CANARY_SECRET}.txt"]
    normalized = normalize.normalize_failure(fixture)
    joined = "\n".join(str(path) for path in normalized.get("artifacts", []))
    assert CANARY_SECRET not in joined


@pytest.mark.xfail(reason="green after K3: review comment body stays clean", strict=False)
def test_canary_never_in_review_comment_body() -> None:
    review_ci = import_module("mergecraft.ci.review")
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("canary_in_ci_log.json")
    normalized = normalize.normalize_failure(fixture)
    body = review_ci.render_ci_failure_comment([normalized])
    assert CANARY_SECRET not in body
