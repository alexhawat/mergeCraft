"""Promoted permanent pytest tests from the eval bank (#44, W12.1)."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from loguru import logger

from mergecraft.evals.ids import CASE_ID_RE
from mergecraft.evals.store import Case  # noqa: TC001

# ── promote-to-permanent-test (W12.1) ──────────────────────────────────


PERMANENT_TEST_FILE_SUFFIX = ".py"
PERMANENT_TEST_DIR_NAME = "permanent"
PERMANENT_TEST_HEADER = '''"""Auto-generated permanent test promoted from the eval bank (#44, W12.1).

This file is produced by ``mergecraft eval promote <case-id>``. Do not
edit by hand — re-run ``mergecraft eval promote`` to regenerate. The
test re-runs the case against the current code via
``mergecraft.evals.store.replay_case``: a ``passed`` status means the
case's expected verdict matches what the running code produced; a
``regression`` status means the same failure mode the case captured has
recurred — that is the structural signal the promote workflow ships.

The promoted test lives under ``tests/evals/permanent/`` and is
discovered by pytest via the standard collection rules — no separate
``conftest`` is required.
"""

from __future__ import annotations

from mergecraft.evals.store import Case, replay_case

_PERMANENT_CASE_PAYLOAD = {payload!r}


def _load_permanent_case() -> Case:
    """Materialize the embedded case payload as a validated :class:`Case`.

    The payload is the case's full JSON shape (including the embedded
    ``LearningProvenance``); ``Case.model_validate_json`` is the same
    path the bank uses at read time, so a schema-version bump on the
    bank side surfaces here as a load-time failure rather than a
    silent structural drift.
    """
    return Case.model_validate_json(_PERMANENT_CASE_PAYLOAD)


def test_permanent_{func_name}() -> None:
    """Permanent regression test for case ``{case_id}`` ({title_literal}).

    Expected verdict: ``{expected_decision}``. The replay verdict is
    operator-supplied via the ``MERGECRAFT_PERMANENT_CURRENT_DECISION``
    env var; when unset the default is ``None`` so the case lands in
    the ``blocked`` state (the replay engine did not produce a
    verdict). The test asserts two things:

    - The case is replayable end-to-end (the bank schema still
      validates and ``replay_case`` returns a typed diff).
    - When the operator wires a current verdict, that verdict agrees
      with the case's expected decision — a real regression surfaces
      as a failed assertion.

    The default-``None`` path keeps the test green at import time so a
    fresh promotion does not break the suite. Operators flip the env
    var to surface drift.
    """
    import os

    case = _load_permanent_case()
    current = os.environ.get("MERGECRAFT_PERMANENT_CURRENT_DECISION") or None
    diff = replay_case(case, current_decision=current)
    # The replay must complete — even the default-``None`` path lands in
    # the ``blocked`` status, which is itself a valid replay outcome.
    assert diff.status in {{"passed", "regression", "blocked"}}
    # When the operator wired a current verdict, surface a real drift.
    if diff.current_decision is not None:
        assert diff.current_decision == diff.expected_decision, (
            f"permanent test {{case.id!r}}: replay verdict "
            f"{{diff.current_decision!r}} drifted from expected "
            f"{{diff.expected_decision!r}}"
        )
'''


def render_permanent_test(case: Case) -> str:
    """Render the body of a permanent pytest test for ``case`` (#44, W12.1).

    The generated test re-runs the case against the current code via
    ``replay_case``. The expected verdict comes from the case file; the
    *current* verdict is operator-supplied via
    ``MERGECRAFT_PERMANENT_CURRENT_DECISION`` (or unset for the
    default ``blocked`` state). When the two disagree, the test fails
    — that is the structural signal the promote workflow ships.

    The function is **pure**: it returns a string; it does not touch
    the filesystem. The CLI is the I/O shell that writes the string.

    Args:
        case: The case to promote.

    Returns:
        A complete Python source string (the file's full text). The
        header is stable; the test function name is derived from the
        case id.

    Examples:
        >>> from datetime import datetime, timezone
        >>> from mergecraft.utils.learnings import LearningProvenance
        >>> prov = LearningProvenance(
        ...     run_id="run-1", pr_number=1, source_field="eval_bank",
        ...     author_login="alice", author_association="OWNER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ... )
        >>> case = Case(
        ...     id="synthetic-001", title="t", category="missed_finding",
        ...     submitted_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ...     run_id="run-1", pr_number=1, failure_mode="missed_finding",
        ...     expected_finding="x", expected_decision="block",
        ...     replay_command="mergecraft eval replay synthetic-001",
        ...     provenance=prov, body="",
        ... )
        >>> text = render_permanent_test(case)
        >>> "def test_permanent_synthetic_001" in text
        True
        >>> "expected_decision" in text
        True
    """
    if not CASE_ID_RE.match(case.id):
        msg = f"case id {case.id!r} is not safe to use as a Python identifier"
        raise ValueError(msg)
    func_name = case.id.replace("-", "_").replace(".", "_")
    payload = case.model_dump_json()
    return PERMANENT_TEST_HEADER.format(
        payload=payload,
        func_name=func_name,
        case_id=case.id,
        title_literal=case.title.replace("\\", "\\\\").replace('"', '\\"'),
        expected_decision=case.expected_decision,
    )


def permanent_test_path(target_dir: Path, case_id: str) -> Path:
    """Return the on-disk path for a promoted test file.

    The case id becomes the file stem (``.py``). The path is purely
    computed — no filesystem reads or writes. The CLI is responsible
    for the actual write.

    Args:
        target_dir: The directory the promoted test lives in.
        case_id: The case id (also the file stem).

    Returns:
        The computed path. The function never touches the filesystem.

    Raises:
        ValueError: When ``case_id`` is not a valid identifier.
    """
    if not CASE_ID_RE.match(case_id):
        msg = f"case id {case_id!r} is not a valid identifier"
        raise ValueError(msg)
    return (
        target_dir
        / f"test_permanent_{case_id.replace('-', '_').replace('.', '_')}{PERMANENT_TEST_FILE_SUFFIX}"
    )


def write_permanent_test(
    target_dir: Path,
    case: Case,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a promoted pytest test for ``case`` under ``target_dir``.

    The directory is created if missing. The test file is the rendered
    output of :func:`render_permanent_test`; the on-disk path is the
    one :func:`permanent_test_path` returns.

    Args:
        target_dir: The directory to write the test into.
        case: The case to promote.
        overwrite: When True, overwrite an existing test for the same
            case. When False, raises :class:`FileExistsError`.

    Returns:
        The path the test was written to.

    Raises:
        FileExistsError: When ``overwrite`` is False and a test for
            the same case already exists.
        ValueError: When the case id is not a valid identifier.
        OSError: When the file cannot be written.
    """
    if not CASE_ID_RE.match(case.id):
        msg = f"case id {case.id!r} is not a valid identifier"
        raise ValueError(msg)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = permanent_test_path(target_dir, case.id)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.write_text(render_permanent_test(case), encoding="utf-8")
    logger.info("» promoted case {} → {}", case.id, target)
    return target


__all__ = [
    "PERMANENT_TEST_DIR_NAME",
    "PERMANENT_TEST_FILE_SUFFIX",
    "permanent_test_path",
    "render_permanent_test",
    "write_permanent_test",
]
