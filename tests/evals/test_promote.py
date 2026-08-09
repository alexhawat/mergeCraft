"""Tests for the promote-to-permanent-test workflow (#44, W12.1).

The promote workflow turns a bank case into a permanent pytest test
under ``tests/evals/permanent/``. The tests in this module pin:

- The renderer's output is a syntactically valid Python module that
  pytest can collect (the function name is derived from the case id;
  the embedded payload round-trips through ``Case.model_validate_json``).
- The writer creates the target directory when missing and respects
  ``overwrite``.
- ``render_permanent_test`` rejects case ids outside the locked shape.
- The generated test imports ``replay_case`` from
  ``mergecraft.evals.store`` — the promote workflow is a thin wrapper
  around the bank's pure replay function.

Fixtures are synthetic (id-prefix ``synthetic``) so the committed
corpus never looks like a real historical failure.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mergecraft.evals.store import (
    Case,
    add_case,
    permanent_test_path,
    render_permanent_test,
    write_permanent_test,
)
from mergecraft.utils.learnings import LearningProvenance

# ── fixtures ───────────────────────────────────────────────────────────


def _provenance() -> LearningProvenance:
    return LearningProvenance(
        run_id="synthetic",
        pr_number=1,
        source_field="eval_bank",
        author_login="synthetic",
        author_association="OWNER",
        trust_tier="trusted",
        timestamp=datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
    )


def _case(**overrides: object) -> Case:
    defaults: dict[str, object] = {
        "id": "synthetic-001",
        "title": "missed a fabricated deletion",
        "category": "missed_finding",
        "submitted_at": datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        "run_id": "synthetic",
        "pr_number": 1,
        "failure_mode": "missed_finding",
        "expected_finding": "src/mergecraft/foo.py:42-60: 'delete' on unborn file",
        "expected_decision": "block",
        "replay_command": "mergecraft eval replay synthetic-001",
        "provenance": _provenance(),
        "body": "# synthetic-001\n\ndescription\n",
    }
    defaults.update(overrides)
    return Case(**defaults)  # type: ignore[arg-type]


# ── permanent_test_path ────────────────────────────────────────────────


def test_permanent_test_path_uses_python_identifier(tmp_path: Path) -> None:
    """The promoted test filename is a Python-safe identifier."""
    path = permanent_test_path(tmp_path, "synthetic-001")
    assert path.name == "test_permanent_synthetic_001.py"


def test_permanent_test_path_rejects_invalid_case_id(tmp_path: Path) -> None:
    """A case id outside the locked shape is rejected."""
    with pytest.raises(ValueError, match="not a valid identifier"):
        permanent_test_path(tmp_path, "has spaces")


# ── render_permanent_test ──────────────────────────────────────────────


def test_render_permanent_test_produces_valid_python() -> None:
    """The rendered module compiles and imports cleanly."""
    case = _case()
    text = render_permanent_test(case)
    # Sanity: compiles without error.
    compile(text, "<promoted-test>", "exec")


def test_render_permanent_test_derives_function_name_from_case_id() -> None:
    """The test function name follows the case id's snake-case shape."""
    text = render_permanent_test(_case(id="synthetic-001"))
    assert "def test_permanent_synthetic_001" in text


def test_render_permanent_test_embeds_case_payload_as_json() -> None:
    """The case payload round-trips through ``Case.model_validate_json``."""
    case = _case()
    text = render_permanent_test(case)
    # The header is supposed to embed the JSON payload as a Python
    # string literal. Extract the literal between ``_PERMANENT_CASE_PAYLOAD = {`` and ``}``
    # and round-trip it.
    start = text.index("_PERMANENT_CASE_PAYLOAD = ") + len("_PERMANENT_CASE_PAYLOAD = ")
    end = text.index("\n\n\ndef", start)
    literal = text[start:end].strip()
    # The literal is a Python string; ``ast.literal_eval`` decodes it.
    import ast

    payload_str = ast.literal_eval(literal)
    parsed = Case.model_validate_json(payload_str)
    assert parsed == case


def test_render_permanent_test_rejects_invalid_case_id() -> None:
    """A case id outside the locked shape is rejected by the renderer.

    The ``Case`` model itself rejects non-identifier ids via its
    validator, so the renderer never has to. This test pins that
    behaviour at the seam: the renderer is *only* fed cases that have
    already cleared the bank's validation.
    """
    with pytest.raises(ValueError, match="is not a valid identifier"):
        _case(id="has spaces")


def test_render_permanent_test_documents_expected_decision() -> None:
    """The test docstring names the case's expected decision."""
    text = render_permanent_test(_case(expected_decision="block"))
    assert "Expected verdict: ``block``" in text


# ── write_permanent_test ───────────────────────────────────────────────


def test_write_permanent_test_creates_file_and_directory(tmp_path: Path) -> None:
    """``write_permanent_test`` creates the target directory when missing."""
    target_dir = tmp_path / "deep" / "nested" / "permanent"
    case = _case()
    target = write_permanent_test(target_dir, case)
    assert target_dir.is_dir()
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == render_permanent_test(case)


def test_write_permanent_test_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    """A second write raises ``FileExistsError`` when ``overwrite`` is False."""
    case = _case()
    write_permanent_test(tmp_path, case)
    with pytest.raises(FileExistsError):
        write_permanent_test(tmp_path, case)


def test_write_permanent_test_overwrites_when_flagged(tmp_path: Path) -> None:
    """``overwrite=True`` replaces the existing promoted test."""
    case = _case()
    write_permanent_test(tmp_path, case)
    target = write_permanent_test(tmp_path, case, overwrite=True)
    assert target.is_file()
    # The re-render must be byte-identical to ``render_permanent_test``.
    assert target.read_text(encoding="utf-8") == render_permanent_test(case)


# ── end-to-end: bank → promote → collect ───────────────────────────────


def test_promote_to_bank_then_to_permanent_test_is_collectible(
    tmp_path: Path,
) -> None:
    """A case promoted from the bank produces a test pytest can collect.

    The promoted test re-runs ``replay_case`` against the embedded
    case. With the default replay verdict (``None``), the diff status
    is ``blocked`` — the assertion accepts that status alongside
    ``passed`` and ``regression``, so a fresh promotion is green.
    """
    bank_dir = tmp_path / "bank"
    permanent_dir = tmp_path / "permanent"
    case = _case()
    add_case(bank_dir, case)

    # Re-read the case from disk (mirrors what the CLI does).
    from mergecraft.evals.store import load_case

    loaded = load_case(bank_dir / "synthetic-001.md")
    target = write_permanent_test(permanent_dir, loaded)
    assert target.is_file()

    # Run pytest on the promoted test; expect one passing test.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "--tb=short",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_promote_default_replay_blocks_until_current_decision_wired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A promotion with no current-decision env var lands in ``blocked``.

    The promoted test is green at import time (the ``blocked`` status
    is acceptable per the assertion), but the moment the operator wires
    ``MERGECRAFT_PERMANENT_CURRENT_DECISION``, a drift surfaces as a
    failing assertion. This test pins both behaviours.
    """
    bank_dir = tmp_path / "bank"
    permanent_dir = tmp_path / "permanent"
    case = _case()
    add_case(bank_dir, case)

    from mergecraft.evals.store import load_case

    loaded = load_case(bank_dir / "synthetic-001.md")
    target = write_permanent_test(permanent_dir, loaded)

    # Default path — no current decision: ``blocked`` is acceptable.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "--tb=short",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # With a drifting current decision: pytest must fail. The case
    # expects ``block``; we supply ``auto_merge`` and the assertion
    # ``diff.current_decision == diff.expected_decision`` fails.
    env = {
        "MERGECRAFT_PERMANENT_CURRENT_DECISION": "auto_merge",
        "PATH": "/usr/bin:/usr/local/bin",
    }
    result2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "--tb=short",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, **env},
    )
    assert result2.returncode != 0, result2.stdout + result2.stderr
    assert "drifted" in result2.stdout or "drifted" in result2.stderr


# ── guard: no inline-narration in the generated test ──────────────────


def test_render_permanent_test_has_no_forbidden_phrase() -> None:
    """The rendered test does not narrate or hand-write a verdict.

    The promoted test is a structural replay against ``replay_case`` —
    no inline verdict narrative that an operator could mutate.
    """
    text = render_permanent_test(_case())
    # Sanity: the structural replay helper is referenced.
    assert "replay_case" in text
    # The text must not embed prose like "I think" / "looks good to me".
    for forbidden in ("I think", "looks good to me", "I recommend"):
        assert forbidden not in text


__all__: list[str] = []
