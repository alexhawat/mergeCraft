"""DG1 baseline suppression — base-vs-head analyzer diffing (G4, D3).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — wired through ``analyzers/config.py::baseComparison``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.analyzers.support import import_module
from tests.findings.support import make_finding


def _head_and_base_hit(*, path: str, line: int, message: str) -> tuple[object, object]:
    finding_mod = import_module("mergecraft.analyzers.finding")
    shared = {
        "tool": "ruff",
        "rule_id": "F401",
        "category": "Maintainability & Code Quality",
        "severity": "Minor",
        "confidence": "certain",
        "message": message,
        "path": path,
        "start_line": line,
        "end_line": line,
        "source": "analyzer",
    }
    head = finding_mod.make_finding(**shared, introduced_by_pr="unknown")
    base = finding_mod.make_finding(**shared, introduced_by_pr="false")
    return head, base


def test_preexisting_analyzer_hit_is_suppressed() -> None:
    """A hit present on base and head on an untouched line is suppressed (D3)."""
    from mergecraft.analyzers.baseline_suppression import suppress_baseline_findings

    head, base = _head_and_base_hit(
        path="src/fixture_app/handler.py",
        line=12,
        message="Unused import os",
    )
    diff_text = "diff --git a/README.md b/README.md\n"

    result = suppress_baseline_findings(
        head_findings=[head],
        base_findings=[base],
        diff_text=diff_text,
        base_comparison="full",
    )

    assert result.suppressed == [head]
    assert result.reported == []


def test_new_hit_on_an_untouched_file_is_still_reported() -> None:
    """The diff can expose a defect on a file it never touched — still report it."""
    from mergecraft.analyzers.baseline_suppression import suppress_baseline_findings

    novel = make_finding(
        tool="ruff",
        rule_id="E722",
        category="Maintainability & Code Quality",
        severity="Major",
        message="Bare except on helper",
        path="src/fixture_app/eval_sink.py",
        start_line=5,
        end_line=5,
        source="analyzer",
        introduced_by_pr="true",
    )
    diff_text = "diff --git a/README.md b/README.md\n"

    result = suppress_baseline_findings(
        head_findings=[novel],
        base_findings=[],
        diff_text=diff_text,
        base_comparison="full",
    )

    assert novel in result.reported
    assert result.suppressed == []


def test_suppression_is_skipped_when_it_cannot_pay_for_itself() -> None:
    """Tiny diffs skip the expensive base run — default ``baseComparison`` is ``diff``."""
    from mergecraft.analyzers.baseline_suppression import should_run_baseline_suppression

    tiny_diff = "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-old\n+new\n"
    settings_mod = import_module("mergecraft.config.settings")
    settings = settings_mod.AnalyzersSettings()

    assert settings.base_comparison == "diff"
    assert (
        should_run_baseline_suppression(
            diff_text=tiny_diff, base_comparison=settings.base_comparison
        )
        is False
    )


def test_suppression_decision_is_auditable() -> None:
    """Every suppression carries an audit trail (convention 7)."""
    from mergecraft.analyzers.baseline_suppression import suppress_baseline_findings

    head, base = _head_and_base_hit(
        path="src/fixture_app/handler.py",
        line=12,
        message="Unused import os",
    )

    result = suppress_baseline_findings(
        head_findings=[head],
        base_findings=[base],
        diff_text="diff --git a/README.md b/README.md\n",
        base_comparison="full",
    )

    assert result.audit_trail
    entry = result.audit_trail[0]
    assert entry.fingerprint == head.fingerprint
    assert entry.decision == "suppressed"
    assert entry.reason


def test_base_collection_failure_is_distinct_from_clean_zero_hits() -> None:
    """An empty base run after failure must not be treated like a clean zero-hit run."""
    from mergecraft.analyzers.baseline_suppression import BaseCollectionResult

    failed = BaseCollectionResult(findings=[], collected=False)
    clean = BaseCollectionResult(findings=[], collected=True)

    assert failed.collected is False
    assert clean.collected is True


def test_base_collection_all_skipped_is_not_collected(monkeypatch, tmp_path: Path) -> None:
    """When every base adapter skips, collection must fail closed (collected=False)."""
    from mergecraft.analyzers import adapters, baseline_suppression, contracts

    worktree = tmp_path / "base-worktree"
    worktree.mkdir()

    monkeypatch.setattr(
        contracts,
        "resolve_analyzer_base_ref",
        lambda *_args, **_kwargs: "base-sha",
    )
    monkeypatch.setattr(
        baseline_suppression,
        "_checkout_base_worktree",
        lambda *_args, **_kwargs: worktree,
    )
    monkeypatch.setattr(
        baseline_suppression, "_remove_base_worktree", lambda *_args, **_kwargs: None
    )

    manifests = [SimpleNamespace(id="ruff"), SimpleNamespace(id="mypy")]

    def _all_skipped(**_kwargs: object) -> adapters.AdapterRunResult:
        return adapters.AdapterRunResult(findings=[], skipped=True, skip_reason="unavailable")

    monkeypatch.setattr(adapters, "run_adapter", _all_skipped)

    result = baseline_suppression.collect_base_analyzer_findings(
        repo_root=tmp_path,
        manifests=manifests,
        changed_files=["src/a.py"],
        head_findings=[],
        tier="trusted",
    )

    assert result.findings == []
    assert result.collected is False


def test_base_collection_fault_isolation_continues_on_adapter_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """One failing base adapter must not abort collection for the rest."""
    from mergecraft.analyzers import adapters, baseline_suppression, contracts

    worktree = tmp_path / "base-worktree"
    worktree.mkdir()

    monkeypatch.setattr(
        contracts,
        "resolve_analyzer_base_ref",
        lambda *_args, **_kwargs: "base-sha",
    )
    monkeypatch.setattr(
        baseline_suppression,
        "_checkout_base_worktree",
        lambda *_args, **_kwargs: worktree,
    )
    monkeypatch.setattr(
        baseline_suppression, "_remove_base_worktree", lambda *_args, **_kwargs: None
    )

    manifests = [SimpleNamespace(id="ruff"), SimpleNamespace(id="mypy")]

    base_hit = make_finding(
        tool="mypy",
        rule_id="error",
        category="Functional Correctness",
        severity="Major",
        message="Type error",
        path="src/a.py",
        start_line=1,
        end_line=1,
        source="analyzer",
    )
    calls: list[str] = []

    def _run_adapter(*, tool_id: str, **_kwargs: object) -> adapters.AdapterRunResult:
        calls.append(tool_id)
        if tool_id == "ruff":
            raise OSError("ruff binary missing")
        return adapters.AdapterRunResult(findings=[base_hit], skipped=False)

    monkeypatch.setattr(adapters, "run_adapter", _run_adapter)

    result = baseline_suppression.collect_base_analyzer_findings(
        repo_root=tmp_path,
        manifests=manifests,
        changed_files=["src/a.py"],
        head_findings=[],
        tier="trusted",
    )

    assert calls == ["ruff", "mypy"]
    assert result.collected is True
    assert result.findings == [base_hit]


def test_apply_baseline_suppression_skips_diff_when_all_adapters_skipped(
    monkeypatch,
) -> None:
    """All-skipped base collection must not mark findings pre-existing via empty base diff."""
    from mergecraft.analyzers import baseline_suppression, pipeline

    head, _base = _head_and_base_hit(
        path="src/fixture_app/handler.py",
        line=12,
        message="Unused import os",
    )

    monkeypatch.setattr(
        baseline_suppression,
        "collect_base_analyzer_findings",
        lambda **_kwargs: baseline_suppression.BaseCollectionResult(
            findings=[],
            collected=False,
        ),
    )

    large_diff = "\n".join(
        [
            "diff --git a/src/a.py b/src/a.py",
            "@@ -1,20 +1,20 @@",
            *(f"+line {index}" for index in range(20)),
        ]
    )

    result = pipeline._apply_baseline_suppression(
        [head],
        repo_root=Path("/tmp/unused"),
        manifests=[],
        changed_files=["src/a.py"],
        diff_text=large_diff,
        base_comparison="full",
        tier="trusted",
        base_ref=None,
        offline=False,
        allow_repo_binaries=True,
    )

    assert result == [head]
    assert head.introduced_by_pr == "unknown"
