"""A read outside the checkout and run tmpdir is recorded, not silently allowed.

Plan 35 found no honest point outside the drivers to mediate reads, so plan 42's
Claude driver denies writes/web/exec and plan 51's read-scoping item adds the
rest: :func:`mergecraft.security.review_integrity.assert_checkout_read_boundary`
runs over the ``Read`` / ``Glob`` / ``Grep`` paths in the tool-call log, and any
path outside the boundary (**checkout union run tmpdir**) becomes a run-record
warning naming the path.

This is detection over the reads that actually happened — not validation of a
guessed list.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from mergecraft.agents import claude as claude_module
from mergecraft.evidence.trajectory import ToolCallRecord

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@contextmanager
def _capture_warnings() -> Iterator[list[str]]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        yield captured
    finally:
        loguru_logger.remove(sink_id)


def _read(sequence: int, tool: str, *paths: str) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool=tool,
        signature=f"{tool}:{paths[0] if paths else ''}",
        intent="read",
        ok=True,
        paths=list(paths),
    )


def _audit(records: Sequence[ToolCallRecord], *, checkout: Path, tmpdir: Path) -> list[str]:
    return claude_module.audit_read_boundary(records, checkout=checkout, tmpdir=tmpdir)


def test_a_read_outside_the_boundary_warns_and_names_the_path(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    run_tmpdir = tmp_path / "run"
    run_tmpdir.mkdir()
    records = [_read(1, "Read", "/etc/passwd")]

    with _capture_warnings() as warnings:
        violations = _audit(records, checkout=checkout, tmpdir=run_tmpdir)

    assert any("/etc/passwd" in violation for violation in violations), (
        f"the out-of-boundary read must be reported; got {violations!r}"
    )
    assert any("/etc/passwd" in message for message in warnings), (
        f"the violation must be recorded as a run-record warning; got {warnings!r}"
    )


def test_reads_inside_the_checkout_or_run_tmpdir_record_nothing(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    run_tmpdir = tmp_path / "run"
    (run_tmpdir / "evidence").mkdir(parents=True)
    (run_tmpdir / "evidence" / "packet.json").write_text("{}", encoding="utf-8")
    records = [
        _read(1, "Read", "src/app.py"),
        _read(2, "Glob", "src/**"),
        _read(3, "Grep", "src/app.py"),
        _read(4, "Read", str(run_tmpdir / "evidence" / "packet.json")),
    ]

    with _capture_warnings() as warnings:
        violations = _audit(records, checkout=checkout, tmpdir=run_tmpdir)

    assert violations == [], f"in-boundary reads must not be reported; got {violations!r}"
    assert warnings == [], f"in-boundary reads must not warn; got {warnings!r}"


def test_non_read_tools_are_not_audited(tmp_path: Path) -> None:
    """Only ``Read`` / ``Glob`` / ``Grep`` name paths the boundary check owns."""
    checkout = tmp_path / "repo"
    checkout.mkdir()
    run_tmpdir = tmp_path / "run"
    run_tmpdir.mkdir()
    records = [
        ToolCallRecord(
            sequence=1,
            tool="Bash",
            signature="Bash:cat",
            intent="read",
            ok=True,
            paths=["/etc/passwd"],
        )
    ]

    with _capture_warnings() as warnings:
        violations = _audit(records, checkout=checkout, tmpdir=run_tmpdir)

    assert violations == []
    assert warnings == []


def test_a_relative_path_escaping_the_checkout_is_reported(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    run_tmpdir = tmp_path / "run"
    run_tmpdir.mkdir()
    records = [_read(1, "Read", "../outside.py")]

    with _capture_warnings() as warnings:
        violations = _audit(records, checkout=checkout, tmpdir=run_tmpdir)

    assert violations, "a `..` escape must resolve outside the boundary and be reported"
    assert warnings
