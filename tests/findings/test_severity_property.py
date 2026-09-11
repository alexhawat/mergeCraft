"""The property N20 is judged by (RA1.2, D15).

No lexical transformation of a finding's prose that preserves its asserted
impact may lower its severity across a blocking boundary. The corpus is a fixed
set of impact statements (security and correctness) crossed with incidental
tokens; the property compares the incidental paraphrase against the same impact
without the token. A fixed two-element case would pass on the wrong fix, so the
property is Hypothesis-driven over the corpus.
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.findings.fixtures.severity_pairs import (
    IMPACT_STATEMENTS,
    INCIDENTAL_TOKENS,
    incidental_message,
)
from tests.findings.support import make_finding


def _normalized(message: str, severity: str) -> Any:
    from mergecraft.findings.severity_rubric import (
        apply_severity_rubric,
        infer_category_from_message,
    )

    category = infer_category_from_message(message)
    finding = make_finding(
        category=category,
        severity=severity,
        message=message,
        path="src/session.py",
        start_line=42,
        end_line=42,
        source="agent",
    )
    return apply_severity_rubric(finding, model_assigned_severity=severity)


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    impact=st.sampled_from(IMPACT_STATEMENTS),
    incidental=st.sampled_from(INCIDENTAL_TOKENS),
)
def test_no_impact_preserving_lexical_change_crosses_a_blocking_boundary(
    impact: tuple[str, str],
    incidental: str,
) -> None:
    severity, impact_message = impact
    control = _normalized(impact_message, severity)
    paraphrased = _normalized(incidental_message(impact_message, incidental), severity)

    assert paraphrased.severity == control.severity, (
        f"incidental {incidental!r} changed {impact_message!r} from "
        f"{control.severity!r} to {paraphrased.severity!r}"
    )
