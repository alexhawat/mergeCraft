"""Redaction work stays linear in the input, and pathological JSON never raises.

These bound the *work* (characters copied, decode attempts, redaction calls,
bytes kept), never wall-clock time.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers import redact
from mergecraft.analyzers import run as run_mod
from mergecraft.analyzers.redact import redact_analyzer_output, redact_secrets
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.utils.json_load import try_load_json, try_load_json_array, try_load_json_object


class _SliceCountingStr(str):
    """A ``str`` that records how many characters its slices copy."""

    copied: int

    def __new__(cls, value: str) -> _SliceCountingStr:
        instance = super().__new__(cls, value)
        instance.copied = 0
        return instance

    def __getitem__(self, key: Any) -> str:
        piece = super().__getitem__(key)
        if isinstance(key, slice):
            self.copied += len(piece)
        return piece


def _lint_dump(lines: int) -> str:
    return "".join(
        f"src/pkg/module_{n}.py:{n}: E501 line too long aVeryLongIdentifierName{n}\n"
        for n in range(lines)
    )


@pytest.mark.parametrize("lines", [500, 4000], ids=["500-lines", "4000-lines"])
def test_entropy_pass_copies_at_most_the_input_once(lines: int) -> None:
    """Each long token used to copy the whole remaining text (quadratic)."""
    text = _SliceCountingStr(_lint_dump(lines))

    redact._entropy_redact(text)

    assert text.copied <= len(text)


def _count_raw_decodes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = json.JSONDecoder.raw_decode

    def counting(self: json.JSONDecoder, s: str, idx: int = 0) -> tuple[Any, int]:
        calls.append(idx)
        return real(self, s, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", counting)
    return calls


@pytest.mark.parametrize("repeats", [1_000, 32_000], ids=["1k", "32k"])
def test_unparsable_braces_cap_decode_attempts(
    monkeypatch: pytest.MonkeyPatch, repeats: int
) -> None:
    raw = '{"a": 1} ' + "{x " * repeats + "token=ghp_" + "A" * 36
    calls = _count_raw_decodes(monkeypatch)

    out = redact_analyzer_output(raw, tool_id="x")

    # json.loads also goes through raw_decode: the JSONL probe, the whole-text
    # parse and the first document add a fixed handful of calls.
    assert len(calls) <= redact._MAX_FAILED_JSON_DECODES + 4
    assert "ghp_" not in out


@pytest.mark.parametrize("depth", [32_000, 200_000], ids=["32k", "200k"])
def test_deeply_nested_output_is_redacted_as_text_without_raising(depth: int) -> None:
    raw = "[" * depth + " password: hunter2"

    out = redact_analyzer_output(raw, tool_id="x")

    assert "hunter2" not in out
    assert out.startswith("[[[[")


def test_deep_but_valid_json_falls_back_to_text_redaction() -> None:
    raw = "[" * 5_000 + '"token=ghp_' + "B" * 36 + '"' + "]" * 5_000
    assert "ghp_" not in redact_analyzer_output(raw, tool_id="x")


@pytest.mark.parametrize(
    "loader",
    [try_load_json, try_load_json_object, try_load_json_array],
    ids=["any", "object", "array"],
)
def test_json_loaders_return_none_on_deep_nesting(loader: Any) -> None:
    assert loader("[" * 200_000) is None


def test_json_loader_bounds_decode_attempts_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "[" * 800 + "x"
    calls = _count_raw_decodes(monkeypatch)

    assert try_load_json_object(raw) is None
    # One attempt per brace (800) used to rescan the rest of the input each time.
    assert len(calls) < 100


def test_json_loader_still_finds_a_value_after_a_few_bad_braces() -> None:
    assert try_load_json_object('progress {x} {y} {"ok": true}') == {"ok": True}


def _plan(tmp_path: Path) -> AnalyzerPlan:
    return AnalyzerPlan(manifest_id="ruff", mode="managed", argv=("ruff", "check"), cwd=tmp_path)


def _spy_redaction(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def spy(raw: str, *, tool_id: str) -> str:
        seen.append(raw)
        return redact_analyzer_output(raw, tool_id=tool_id)

    monkeypatch.setattr(run_mod, "redact_analyzer_output", spy)
    return seen


def test_each_captured_stream_is_redacted_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _spy_redaction(monkeypatch)
    stdout = _lint_dump(400)
    stderr = "warning: cache dir not writable"
    completed = subprocess.CompletedProcess(
        args=["ruff"], returncode=1, stdout=stdout, stderr=stderr
    )

    outcome = run_mod._outcome_from_completed(
        completed, plan=_plan(tmp_path), command="ruff check", output_dir=tmp_path
    )

    assert seen == [stdout.strip(), stderr]
    assert outcome.output_path is not None
    assert Path(outcome.output_path).read_text(encoding="utf-8") == redact_secrets(stdout.strip())


def test_captured_output_is_capped_before_redaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_CHARS", 1_000)
    seen = _spy_redaction(monkeypatch)
    completed = subprocess.CompletedProcess(
        args=["ruff"], returncode=1, stdout=_lint_dump(400), stderr=""
    )

    outcome = run_mod._outcome_from_completed(
        completed, plan=_plan(tmp_path), command="ruff check", output_dir=tmp_path
    )

    assert [len(raw) <= 1_000 for raw in seen] == [True]
    assert outcome.output_path is not None
    assert len(Path(outcome.output_path).read_text(encoding="utf-8")) <= 1_000
    assert "exceeded 1000 chars" in outcome.output
