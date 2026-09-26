"""C7 — docs and action input describe review-only behaviour (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decision **PD-D7** — correct prose; remove no input, key or module.
Production registers only review-capable modes, so the ``push`` input refuses
commit/push whatever its value and no value grants write access. The
``REVIEW-CHECKS.md`` §9 heading is kept for anchor stability while the claim is
corrected: the address-reviews mode is not registered in production.

These assertions fail until PD3; do not xfail: RED is the point.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from tests.ci.workflow_support import REPO_ROOT

_ACTION_YML = REPO_ROOT / "action.yml"
_ACTION_REFERENCE = REPO_ROOT / "docs" / "action-reference.md"
_REVIEW_CHECKS = REPO_ROOT / "REVIEW-CHECKS.md"


def _action_input_description(name: str) -> str:
    data: Any = yaml.safe_load(_ACTION_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "action.yml must parse as a mapping"
    inputs = data.get("inputs")
    assert isinstance(inputs, dict), "action.yml must declare inputs"
    entry = inputs.get(name)
    assert isinstance(entry, dict), f"action.yml must declare the {name!r} input"
    description = entry.get("description")
    assert isinstance(description, str), f"action.yml {name!r} input has no description"
    return description


def _action_reference_row(name: str) -> str:
    text = _ACTION_REFERENCE.read_text(encoding="utf-8")
    match = re.search(rf"^\|\s*`{re.escape(name)}`\s*\|.*$", text, re.MULTILINE)
    assert match, f"docs/action-reference.md has no `{name}` input row"
    return match.group(0)


def _review_checks_section_9() -> str:
    text = _REVIEW_CHECKS.read_text(encoding="utf-8")
    start = re.search(r"^## 9\.\s", text, re.MULTILINE)
    assert start, "REVIEW-CHECKS.md must keep its §9 heading for anchor stability (PD-D7)"
    rest = text[start.start() :]
    end = re.search(r"^## 10\.\s", rest, re.MULTILINE)
    return rest if end is None else rest[: end.start()]


def _assert_review_only_refusal(description: str, label: str) -> None:
    lowered = description.lower()
    assert "review-only" in lowered, (
        f"{label} must state production modes are review-only (PD-D7): {description!r}"
    )
    assert "refuse" in lowered, (
        f"{label} must state commit/push are refused whatever the value (PD-D7): {description!r}"
    )
    assert "write" in lowered, (
        f"{label} must state no value grants write access (PD-D7): {description!r}"
    )


def test_action_yml_push_description_states_review_only_refusal() -> None:
    _assert_review_only_refusal(_action_input_description("push"), "action.yml `push`")


def test_action_reference_push_row_states_review_only_refusal() -> None:
    _assert_review_only_refusal(_action_reference_row("push"), "docs/action-reference.md `push`")


def test_review_checks_section_9_does_not_present_address_reviews_as_production() -> None:
    section = _review_checks_section_9()
    lowered = section.lower()
    assert "production" in lowered, "REVIEW-CHECKS.md §9 must state production behaviour (PD-D7)"
    assert "not registered" in lowered, (
        "REVIEW-CHECKS.md §9 must state the address-reviews mode is not registered "
        f"in production (PD-D7); got: {section[:400]!r}"
    )
