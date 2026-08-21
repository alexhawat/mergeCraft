"""W8 / W13 — memory validation, org backend, effectiveness (#360).

Does not produce dismissal reason codes (that is #355 / W10). This wave
consumes that signal; it does not create it.
TTL / contradiction helpers already ship in ``utils/memory.py`` (DG7) —
this file pins the remaining #360 surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from tests.support.cc_batch import (
    MEMORY_KINDS,
    invoke,
    load_module,
    plain,
    require_callable,
    require_registered,
)

_W13 = pytest.mark.xfail(
    reason="green after W13: memory validation / org / effectiveness (#360)",
    strict=False,
)


def _memory_api() -> Any:
    return load_module("mergecraft.memory")


def test_memory_validate_is_currently_a_usage_error() -> None:
    """W8 current state: ``memory validate`` is not registered."""
    result = invoke("memory", "validate", "--help")
    assert result.exit_code == CLI_USAGE_EXIT_CODE, plain(result.stdout + result.stderr)


@_W13
def test_memory_validate_help_is_registered() -> None:
    """#360 — ``mergecraft memory validate`` exists."""
    result = require_registered("memory", "validate", "--help", label="mergecraft memory validate")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "valid" in help_text


@_W13
def test_memory_validate_rejects_a_corrupt_store(tmp_path: Path) -> None:
    """Error: validate exits non-zero on a corrupt memory store."""
    require_registered("memory", "validate", "--help", label="mergecraft memory validate")
    repo = tmp_path / "repo"
    (repo / ".mergecraft").mkdir(parents=True)
    (repo / ".mergecraft" / "learnings.md").write_text("not a memory document\n", encoding="utf-8")
    result = invoke("memory", "validate", "--repo", str(repo))
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, plain(result.stdout + result.stderr)


@_W13
def test_historical_validation_is_required_before_activation() -> None:
    """#360 — learned behaviour is not activated without historical validation."""
    module = _memory_api()
    activate = require_callable(module, "activate_learned_behaviour")
    with pytest.raises(
        (ValueError, RuntimeError, PermissionError),
        match=r"histor|valid|evidence|approv",
    ):
        activate(entry={"id": "one-shot", "text": "ignore style nits"}, evidence_count=1)


@_W13
def test_one_reviewer_action_does_not_silently_create_durable_memory() -> None:
    """#360 — require repeated evidence or explicit approval."""
    module = _memory_api()
    ingest = require_callable(module, "ingest_reviewer_signal")
    result = ingest(action="dismiss", evidence_count=1, approved=False)
    durable = getattr(result, "durable", None)
    if durable is None:
        durable = result.get("durable")
    assert durable is False


@_W13
def test_memory_kinds_are_separated() -> None:
    """#354/#360 — factual / policy / preference / FP suppression stay distinct."""
    module = _memory_api()
    kinds = frozenset(module.MEMORY_KINDS)
    assert kinds == MEMORY_KINDS


@_W13
def test_false_positive_memory_has_expiry_scope_and_over_suppression_guard() -> None:
    """#360 — FP memory expires, is scoped, and cannot over-suppress."""
    module = _memory_api()
    store = require_callable(module, "FalsePositiveMemory")(ttl_days=30, scope="tests/**")
    store.add(pattern="unused import", path_scope="tests/**")
    report = require_callable(module, "detect_over_suppression")(
        store,
        total_findings=10,
        suppressed=9,
    )
    assert report.is_over_suppressed is True


@_W13
def test_organization_memory_backend_is_pluggable() -> None:
    """#360 — org memory is a backend beside the local store."""
    module = _memory_api()
    backend_cls = getattr(module, "OrganizationMemoryBackend", None)
    if backend_cls is None:
        backend_cls = getattr(module, "MemoryBackend", None)
    assert backend_cls is not None
    for name in ("get", "put", "list"):
        assert callable(getattr(backend_cls, name, None)) or hasattr(backend_cls, name)


@_W13
def test_memory_effectiveness_improves_precision_without_reducing_recall() -> None:
    """#360 — effectiveness metrics prove precision up, recall not down."""
    module = _memory_api()
    report = require_callable(module, "evaluate_memory_effectiveness")()
    precision_delta = float(report.precision_delta)
    recall_delta = float(report.recall_delta)
    assert precision_delta > 0.0
    assert recall_delta >= 0.0


@_W13
def test_w13_consumes_dismissal_codes_it_does_not_define_them() -> None:
    """#360 out of scope — dismissal reason codes stay in findings/materiality (#355)."""
    module = _memory_api()
    consume = require_callable(module, "ingest_dismissal_signal")
    consume(reason_code="false_positive", fingerprint="fp-1", evidence_count=3)
    assert not hasattr(module, "DISMISSAL_REASON_CODES")
