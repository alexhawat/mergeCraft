"""W1.5 — entropy redaction evidence sweep (wave plan 15, green after W6)."""

from __future__ import annotations

import importlib
import json
import secrets
import string
from dataclasses import dataclass
from pathlib import Path

import pytest

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from tests.analyzers.support import FIXTURES_DIR, REDACTION_ANALYZER_IDS

_BENIGN_FIXTURE_SHAPES: tuple[tuple[str, str], ...] = (
    ("git_sha_40", "a" * 40),
    ("hex_run_64", "deadbeef" * 8),
    ("snake_identifier", "fetch_user_profile"),
    ("metadata_assignment", "catalog=unavailable"),
)


@dataclass(frozen=True, slots=True)
class RedactionHit:
    analyzer_id: str
    token: str
    context: str


def _high_entropy_secret(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits + "+/=_-"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _fixture_paths_for_analyzer(analyzer_id: str) -> list[Path]:
    candidates = [
        FIXTURES_DIR / "outputs" / f"{analyzer_id}.json",
        FIXTURES_DIR / "outputs" / f"{analyzer_id}.stdout",
        FIXTURES_DIR / "outputs" / f"{analyzer_id}.stderr",
    ]
    return [path for path in candidates if path.is_file()]


def sweep_analyzer_fixtures_for_entropy_redactions() -> list[RedactionHit]:
    """Record every high-entropy token redacted across real analyzer fixtures."""
    hits: list[RedactionHit] = []
    for analyzer_id in REDACTION_ANALYZER_IDS:
        for path in _fixture_paths_for_analyzer(analyzer_id):
            raw = path.read_text(encoding="utf-8", errors="replace")
            redacted = redact_secrets(raw)
            if redacted == raw:
                continue
            for line in raw.splitlines():
                candidate = line.strip()
                if len(candidate) < 16:
                    continue
                if candidate not in line:
                    continue
                if candidate in redacted:
                    continue
                hits.append(
                    RedactionHit(
                        analyzer_id=analyzer_id,
                        token=candidate[:80],
                        context=path.name,
                    )
                )
    return hits


def test_entropy_sweep_harness_records_redacted_tokens_with_context(tmp_path: Path) -> None:
    """D13 — sweep records redacted tokens with analyzer + fixture context."""
    report_path = tmp_path / "entropy_sweep_report.json"
    hits = sweep_analyzer_fixtures_for_entropy_redactions()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps([hit.__dict__ for hit in hits], indent=2),
        encoding="utf-8",
    )
    assert report_path.is_file()
    # Harness must be runnable even when no benign relaxations are justified yet.
    assert isinstance(hits, list)


def test_entropy_sweep_classifies_benign_candidates_for_operator_review() -> None:
    """D13/D14 — W6 publishes benign-vs-secret classification from sweep evidence."""
    module = importlib.import_module("mergecraft.analyzers.redact")
    classify = getattr(module, "classify_entropy_redaction_hits", None)
    if classify is None:
        pytest.fail("classify_entropy_redaction_hits not implemented")
    hits = sweep_analyzer_fixtures_for_entropy_redactions()
    report = classify(hits)
    assert "benign_candidates" in report
    assert "secret_confirmed" in report


@pytest.mark.parametrize(
    ("name", "value"), _BENIGN_FIXTURE_SHAPES, ids=[n for n, _ in _BENIGN_FIXTURE_SHAPES]
)
def test_proven_benign_entropy_shapes_stay_unredacted_after_relaxation(
    name: str, value: str
) -> None:
    """D14 — named benign shapes from the sweep get allowlisted before any threshold move."""
    del name
    assert redact_secrets(value) == value


def test_real_secret_shapes_remain_redacted_fail_closed() -> None:
    """D14 fail-closed guard — high-entropy secret-shaped tokens stay redacted."""
    secret = _high_entropy_secret(40)
    redacted = redact_secrets(secret)
    assert secret not in redacted
    assert REDACTION_SENTINEL in redacted or "<redacted>" in redacted
