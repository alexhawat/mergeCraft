"""W9 — published, reproducible benchmark numbers (#140). S5 prompt versions have landed."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from tests.ci.workflow_support import REPO_ROOT, read_text

from mergecraft.agents.verifier import VERIFIER_RUBRIC_VERSION, JudgePin, judge_pin
from mergecraft.modes import compute_prompt_version

_W9 = pytest.mark.xfail(
    reason="green after W9: publish reproducible benchmark numbers (#140)",
    strict=False,
)

_EVAL_HEADING = re.compile(r"eval infrastructure", re.IGNORECASE)
_METRICS = (
    re.compile(r"precision", re.IGNORECASE),
    re.compile(r"recall", re.IGNORECASE),
    re.compile(r"\bF1\b", re.IGNORECASE),
    re.compile(r"false[\s-]*positive|FP[\s-]*rate", re.IGNORECASE),
)
_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


def _result_files() -> list[Path]:
    roots = [REPO_ROOT / "evals" / "results", REPO_ROOT / "evals" / "benchmark"]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(root.rglob("*.json"))
        found.extend(root.rglob("*.jsonl"))
    return found


@_W9
def test_readme_eval_claim_adjacent_to_dated_metrics_and_corpus_commit() -> None:
    """Do not invent numbers — require a dated precision/recall/F1 + FP-rate + corpus SHA."""
    text = read_text("README.md")
    match = _EVAL_HEADING.search(text)
    assert match is not None, "README eval claim missing"
    start = max(0, match.start() - 800)
    end = min(len(text), match.end() + 1600)
    window = text[start:end]
    missing = [pattern.pattern for pattern in _METRICS if not pattern.search(window)]
    assert not missing, f"README eval claim is not adjacent to metrics {missing}"
    assert _DATE.search(window), "benchmark numbers must be dated"
    assert _SHA.search(window), "corpus commit SHA missing next to the eval claim"


@_W9
def test_replay_target_or_job_exists_and_is_documented() -> None:
    makefile = read_text("Makefile")
    has_make = re.search(r"^(eval-replay|bench-review|eval-gate)\s*:", makefile, re.MULTILINE)
    assert has_make is not None
    # Structural eval-gate already exists; W9 must add a behavioural replay path.
    assert re.search(r"^eval-replay\s*:", makefile, re.MULTILINE) or _workflow_has_replay(), (
        "no eval-replay Make target or CI replay job"
    )
    docs = read_text("evals/README.md") + read_text("README.md")
    assert re.search(r"replay", docs, re.IGNORECASE)


def _workflow_has_replay() -> bool:
    workflows = REPO_ROOT / ".github" / "workflows"
    for path in workflows.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"eval-replay|eval replay|benchmark replay", text, re.IGNORECASE):
            return True
    return False


@_W9
def test_result_set_records_judge_pins_rubric_and_prompt_versions() -> None:
    """Every published result set names judge pins, rubric versions, and S5 prompt versions."""
    files = _result_files()
    assert files, "no evals/results (or evals/benchmark) result set on disk"
    blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
    lowered = blob.lower()
    assert "judge" in lowered or "JudgePin" in blob
    assert "rubric" in lowered
    assert "prompt" in lowered
    assert "version" in lowered

    pin = judge_pin(provider="claude")
    assert isinstance(pin, JudgePin)
    assert pin.rubric_version == VERIFIER_RUBRIC_VERSION
    assert compute_prompt_version("stable") == compute_prompt_version("stable")
    parsed: list[Any] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            parsed.extend(json.loads(line) for line in text.splitlines() if line.strip())
        else:
            parsed.append(json.loads(text))
    serialized = json.dumps(parsed)
    assert VERIFIER_RUBRIC_VERSION in serialized or "rubric_version" in serialized
    assert "prompt_version" in serialized or "compute_prompt_version" in serialized


@_W9
def test_published_metrics_are_not_placeholders() -> None:
    """Refuse fabricated TBD / 0.00 / lorem tables next to the eval claim."""
    text = read_text("README.md")
    match = _EVAL_HEADING.search(text)
    assert match is not None
    window = text[max(0, match.start() - 400) : match.end() + 1600]
    assert not re.search(r"\bTBD\b|\blorem\b|TODO: publish", window, re.IGNORECASE)


def test_s5_prompt_version_helper_is_available() -> None:
    """S5 landed — W9 numbers can name the prompt they ran against."""
    assert compute_prompt_version("a") != compute_prompt_version("b")
    pin = judge_pin(provider="claude")
    assert pin.rubric_version == VERIFIER_RUBRIC_VERSION
