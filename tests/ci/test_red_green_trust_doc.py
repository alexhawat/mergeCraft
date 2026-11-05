"""The receipt doc's trust story names what a ``pull_request`` run executes (#1056 part 5).

A ``pull_request`` run executes the head's code: its tests, its ``conftest.py`` and
any script the workflow calls. A receipt therefore proves what the head's own test
run reported, and is no defence against an author with push access. The doc must
say so, must tell the consumer to write the receipt inline in the declared
workflow rather than from a head-tree script, and its sample must not call one.
"""

from __future__ import annotations

import re
from pathlib import Path

_DOC = Path(__file__).resolve().parents[2] / "docs" / "red-green-receipts.md"
_HEAD_SCRIPT = "scripts/write_red_green_receipt.py"
_RETIRED_SENTENCE = (
    "Who may change the workflow that writes it is the same question as who may change "
    "any other required check"
)


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _section(title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", _text(), re.S | re.M)
    assert match is not None, f"docs/red-green-receipts.md has no '## {title}' section"
    return match.group(1)


def _yaml_blocks() -> list[str]:
    return re.findall(r"```ya?ml\n(.*?)```", _text(), re.S)


def test_the_trust_section_says_a_pull_request_run_executes_head_side_code() -> None:
    trust = _section("Trust")

    assert "head-side" in trust
    assert "conftest.py" in trust
    assert "pull_request" in trust


def test_the_trust_section_says_a_receipt_is_no_defence_against_push_access() -> None:
    assert "push access" in _section("Trust")


def test_the_doc_says_to_write_the_receipt_inline_in_the_declared_workflow() -> None:
    assert "inline" in _text()


def test_the_retired_required_check_sentence_is_gone() -> None:
    assert _RETIRED_SENTENCE not in _text()


def test_the_sample_workflow_does_not_call_a_head_tree_script() -> None:
    blocks = _yaml_blocks()
    workflow_samples = [block for block in blocks if "upload-artifact" in block]

    assert workflow_samples, "the doc keeps a sample workflow that uploads the receipt"
    for block in workflow_samples:
        assert _HEAD_SCRIPT not in block
        assert "red-green.json" in block


def test_the_doc_no_longer_points_at_a_head_tree_converter_script() -> None:
    assert _HEAD_SCRIPT not in _text()
