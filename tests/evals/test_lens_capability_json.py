"""CE #455 RED — stable JSON emission for per-lens capability numbers (D6).

Output must be diffable across commits: sorted keys, fixed float formatting,
and a content digest that ignores key order in the Python object graph.
"""

from __future__ import annotations

import json

from tests.evals.support_lens_capability import (
    require_callable,
    routing_label,
    routing_outcome,
)

_GOLDEN_JSON = (
    '{"by_lens":{"security":{"false_negatives":0,"false_positives":0,'
    '"lens_id":"security","precision":1.0,"recall":1.0,"true_positives":1}},'
    '"cases":1,"macro_f1":1.0,"macro_precision":1.0,"macro_recall":1.0,'
    '"schema_version":"1.0.0"}'
)


def _sample_report() -> object:
    score = require_callable("score_lens_routing")
    return score(
        [routing_label("case-a", "security")],
        [routing_outcome("case-a", "security")],
    )


def test_render_lens_capability_json_is_canonical_and_sorted() -> None:
    """Happy — JSON uses sorted keys and compact separators for stable diffs."""
    render = require_callable("render_lens_capability_json")
    payload = render(_sample_report())
    assert payload == _GOLDEN_JSON
    parsed = json.loads(payload)
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert list(parsed["by_lens"].keys()) == ["security"]


def test_lens_capability_digest_is_stable_for_identical_reports() -> None:
    """Happy — identical routing scores produce identical digests."""
    digest = require_callable("lens_capability_digest")
    report = _sample_report()
    first = digest(report)
    second = digest(report)
    assert first == second
    assert len(first) == 64


def test_lens_capability_digest_ignores_dict_insertion_order() -> None:
    """Edge — digest is over canonical JSON, not Python dict iteration order."""
    digest = require_callable("lens_capability_digest")
    render = require_callable("render_lens_capability_json")
    report = _sample_report()
    from_payload = json.loads(render(report))
    reordered = {
        "macro_recall": from_payload["macro_recall"],
        "schema_version": from_payload["schema_version"],
        "by_lens": from_payload["by_lens"],
        "cases": from_payload["cases"],
        "macro_precision": from_payload["macro_precision"],
        "macro_f1": from_payload["macro_f1"],
    }
    report_cls = type(report)
    round_tripped = report_cls.model_validate(reordered)
    assert digest(report) == digest(round_tripped)
