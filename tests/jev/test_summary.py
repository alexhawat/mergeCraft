"""#786 — Jev review summary section: advisory, absent when disabled, skip-aware."""

from __future__ import annotations

from mergecraft.jev.summary import render_jev_review_section

_MODEL = "jev-1.13.0"


def test_disabled_renders_nothing() -> None:
    """Disabled must be a hard no-op — no empty section, no 'disabled' line."""
    section = render_jev_review_section(
        enabled=False,
        skip_reason=None,
        predictions=None,
        model=_MODEL,
    )
    assert section is None


def test_disabled_renders_nothing_even_with_stale_skip_reason_or_predictions() -> None:
    """``enabled`` alone gates the section — stale leftover state must not leak one in."""
    section = render_jev_review_section(
        enabled=False,
        skip_reason="credential_absent",
        predictions=[{"unit_id": "hunk:a.py:aaaa", "choice": "likely", "confidence": 0.9}],
        model=_MODEL,
    )
    assert section is None


def test_enabled_but_skipped_renders_the_skip_reason() -> None:
    """A missing credential must not look like a clean run (#775-shaped defect)."""
    section = render_jev_review_section(
        enabled=True,
        skip_reason="credential_absent",
        predictions=None,
        model=_MODEL,
    )
    assert section is not None
    assert "credential_absent" in section
    assert "TYPESAFE_API_KEY" in section


def test_kill_switch_skip_reason_is_rendered() -> None:
    section = render_jev_review_section(
        enabled=True,
        skip_reason="kill_switch",
        predictions=None,
        model=_MODEL,
    )
    assert section is not None
    assert "kill_switch" in section


def test_section_states_it_is_advisory_when_skipped() -> None:
    section = render_jev_review_section(
        enabled=True,
        skip_reason="credential_absent",
        predictions=None,
        model=_MODEL,
    )
    assert section is not None
    lowered = section.lower()
    assert "advisory" in lowered
    assert "never skips the reviewer" in lowered or "never" in lowered


def test_section_states_it_is_advisory_when_predictions_present() -> None:
    section = render_jev_review_section(
        enabled=True,
        skip_reason=None,
        predictions=[
            {
                "unit_id": "hunk:src/auth.py:abcd1234",
                "lane": "security",
                "choice": "likely",
                "severity": "Major",
                "confidence": 0.82,
            }
        ],
        model=_MODEL,
    )
    assert section is not None
    assert "advisory" in section.lower()
    assert "enforced" in section.lower()


def test_section_never_implies_calibration() -> None:
    section = render_jev_review_section(
        enabled=True,
        skip_reason=None,
        predictions=[],
        model=_MODEL,
    )
    assert section is not None
    lowered = section.lower()
    assert "unmeasured" in lowered
    assert "are calibrated" not in lowered
    assert "not calibrated" in lowered or "uncalibrated" in lowered


def test_ran_with_no_residual_units_still_states_zero_flagged() -> None:
    section = render_jev_review_section(
        enabled=True,
        skip_reason=None,
        predictions=[],
        model=_MODEL,
    )
    assert section is not None
    assert "0 units" in section
    assert "0 flagged" in section


def test_ran_with_predictions_renders_a_row_per_unit() -> None:
    predictions = [
        {
            "unit_id": "hunk:src/auth.py:abcd1234",
            "lane": "security",
            "choice": "likely",
            "severity": "Major",
            "confidence": 0.82,
        },
        {
            "unit_id": "hunk:src/util.py:ffff0000",
            "lane": "test-gap",
            "choice": "clean",
            "severity": "Trivial",
            "confidence": 0.31,
        },
    ]
    section = render_jev_review_section(
        enabled=True,
        skip_reason=None,
        predictions=predictions,
        model=_MODEL,
    )
    assert section is not None
    assert "2 units" in section
    assert "1 flagged" in section  # only the non-"clean" choice counts as flagged
    assert "hunk:src/auth.py:abcd1234" in section
    assert "hunk:src/util.py:ffff0000" in section
    assert _MODEL in section


def test_never_uses_the_word_enforced_true() -> None:
    """A confident-looking table must never read as a verdict (predict_jev_action, D7)."""
    section = render_jev_review_section(
        enabled=True,
        skip_reason=None,
        predictions=[
            {"unit_id": "u1", "choice": "certain", "severity": "Critical", "confidence": 0.99}
        ],
        model=_MODEL,
    )
    assert section is not None
    lowered = section.lower()
    assert "enforced: true" not in lowered
    assert "enforced" in lowered
    assert "false" in lowered
