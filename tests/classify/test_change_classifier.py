"""AP4 change classifier suite — typed change/risk map (AP4.1 RED).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP4).
Covers ``mergecraft.classify.change_classifier`` — a cheap classifier that
emits a typed change/risk map and reuses ``classify_blast_radius`` for
``risk_band``. Implementation lands in AP4.2.
"""

from __future__ import annotations

from typing import Any

from mergecraft.classify.blast_radius import classify_blast_radius


def _change(*paths: str, **signals: object) -> dict[str, object]:
    return {"changed_paths": list(paths), "diff_stats": signals}


def _classify_change(*args: Any, **kwargs: Any) -> Any:
    from mergecraft.classify.change_classifier import classify_change

    return classify_change(*args, **kwargs)


def test_emits_typed_risk_and_change_map() -> None:
    """Classifier returns a typed change/risk map with blast-radius alignment."""
    change = _change(
        "src/mergecraft/billing/checkout.py",
        files_changed=1,
        lines_added=12,
        lines_deleted=3,
        diff="@@ charge_amount @@",
    )
    result = _classify_change(change)

    assert result.risk_band in {"low", "medium", "high"}
    assert isinstance(result.change_map, dict)
    assert result.change_map.get("changed_paths") == change["changed_paths"]
    assert isinstance(result.change_map.get("categories"), list)
    assert result.blast_radius.lane == result.risk_band
    assert isinstance(result.is_trivial, bool)


def test_detects_generated_and_vendored_files() -> None:
    """Generated and vendored paths are surfaced explicitly in the change map."""
    change = _change(
        "src/generated/schema.py",
        "vendor/acme/widget.py",
        "third_party/lib/foo.c",
        files_changed=3,
    )
    result = _classify_change(change)

    generated = result.change_map.get("generated_paths")
    vendored = result.change_map.get("vendored_paths")
    assert isinstance(generated, list)
    assert isinstance(vendored, list)
    assert "src/generated/schema.py" in generated
    assert "vendor/acme/widget.py" in vendored
    assert "third_party/lib/foo.c" in vendored


def test_risk_band_reflects_blast_radius() -> None:
    """``risk_band`` is derived from ``classify_blast_radius``, not a second rule set."""
    change = _change(
        "migrations/20260816_add_invoice_index.sql",
        files_changed=1,
        diff="ALTER TABLE invoices ADD COLUMN status text;",
    )
    expected = classify_blast_radius(change)

    result = _classify_change(change)

    assert result.risk_band == expected.lane
    assert result.blast_radius == expected


def test_classifier_makes_one_cheap_call() -> None:
    """The classifier agent runs exactly once per classification (cheap gate)."""
    change = _change("docs/guide.md", files_changed=1, lines_added=1, lines_deleted=1)
    calls: list[dict[str, object]] = []

    def _agent_runner(*, change_payload: dict[str, object], **kwargs: object) -> dict[str, object]:
        calls.append({"change": change_payload, **kwargs})
        return {"summary": "doc typo"}

    _classify_change(change, agent_runner=_agent_runner)

    assert len(calls) == 1, "classifier must make exactly one cheap agent call"
