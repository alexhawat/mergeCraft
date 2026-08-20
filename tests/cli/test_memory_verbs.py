"""DG7 memory lifecycle CLI verbs.

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG7).
Implementation: **DG7.2** — ``mergecraft memory list|show|forget|export|import``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.utils.learnings import LearningProvenance, route_learnings_for_persist

runner = CliRunner()


def _provenance(*, run_id: str = "run-1") -> LearningProvenance:
    return LearningProvenance(
        run_id=run_id,
        pr_number=7,
        source_field="learnings_md",
        author_login="alice",
        author_association="MEMBER",
        trust_tier="trusted",
        timestamp=datetime(2026, 8, 18, tzinfo=UTC),
    )


def test_list_show_forget_export_import(tmp_path: Path) -> None:
    """Memory verbs round-trip repo-scoped entries through export/import."""
    repo = tmp_path / "repo"
    repo.mkdir()
    learnings = repo / ".mergecraft" / "learnings.md"
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text(
        "# Learnings\n\n## Active\n\n- keep timeouts on retry loops\n",
        encoding="utf-8",
    )

    list_result = runner.invoke(app, ["memory", "list", "--repo", str(repo), "--json"])
    assert list_result.exit_code == 0, list_result.stdout
    listed = json.loads(list_result.stdout)["entries"]
    assert listed

    memory_id = listed[0]["id"]
    show_result = runner.invoke(app, ["memory", "show", memory_id, "--repo", str(repo), "--json"])
    assert show_result.exit_code == 0, show_result.stdout
    shown = json.loads(show_result.stdout)
    assert shown["id"] == memory_id

    export_path = tmp_path / "memory-export.json"
    export_result = runner.invoke(
        app,
        ["memory", "export", "--repo", str(repo), "--output", str(export_path)],
    )
    assert export_result.exit_code == 0, export_result.stdout
    assert export_path.is_file()

    import_repo = tmp_path / "import-target"
    import_repo.mkdir()
    import_result = runner.invoke(
        app,
        ["memory", "import", str(export_path), "--repo", str(import_repo)],
    )
    assert import_result.exit_code == 0, import_result.stdout

    forget_result = runner.invoke(app, ["memory", "forget", memory_id, "--repo", str(repo)])
    assert forget_result.exit_code == 0, forget_result.stdout
    after_forget = runner.invoke(app, ["memory", "list", "--repo", str(repo), "--json"])
    assert after_forget.exit_code == 0, after_forget.stdout
    remaining = json.loads(after_forget.stdout)["entries"]
    assert all(entry["id"] != memory_id for entry in remaining)


def test_proposed_memory_requires_activation() -> None:
    """Regression pin: proposed learnings stay staged unless ``autopromoteLearnings`` is set."""
    seed = "# Learnings\n\n## Build\n- keep this\n"
    proposed = "- reviewer noticed this rule during the run"
    agent_written = f"{seed}\n## Review memory\n{proposed}\n"

    quarantined = route_learnings_for_persist(
        current=agent_written,
        seed=seed,
        provenance=_provenance(),
        autopromote=False,
    )
    assert quarantined is not None
    active_part, staging_part = quarantined.split("## Staging", 1)
    assert proposed not in active_part
    assert proposed in staging_part

    promoted = route_learnings_for_persist(
        current=agent_written,
        seed=seed,
        provenance=_provenance(run_id="run-2"),
        autopromote=True,
    )
    assert promoted is not None
    active_part, staging_part = promoted.split("## Staging", 1)
    assert proposed in active_part
    assert proposed not in staging_part


def test_import_preserves_legacy_flat_learnings_bullet(tmp_path: Path) -> None:
    """Importing into legacy flat learnings keeps pre-existing bullets."""
    repo = tmp_path / "repo"
    repo.mkdir()
    learnings = repo / ".mergecraft" / "learnings.md"
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text(
        "# Learnings\n\n- keep timeouts on retry loops\n",
        encoding="utf-8",
    )

    export_path = tmp_path / "memory-export.json"
    export_repo = tmp_path / "export-source"
    export_repo.mkdir()
    (export_repo / ".mergecraft").mkdir(parents=True)
    (export_repo / ".mergecraft" / "learnings.md").write_text(
        "# Learnings\n\n## Active\n\n- imported memory bullet\n",
        encoding="utf-8",
    )
    export_result = runner.invoke(
        app,
        ["memory", "export", "--repo", str(export_repo), "--output", str(export_path)],
    )
    assert export_result.exit_code == 0, export_result.stdout

    import_result = runner.invoke(
        app,
        ["memory", "import", str(export_path), "--repo", str(repo)],
    )
    assert import_result.exit_code == 0, import_result.stdout

    remaining_text = learnings.read_text(encoding="utf-8")
    assert "keep timeouts on retry loops" in remaining_text
    assert "imported memory bullet" in remaining_text
    assert "## Active" not in remaining_text


def test_forget_removes_legacy_flat_learnings_bullet(tmp_path: Path) -> None:
    """Legacy learnings without section headings lose the targeted bullet."""
    repo = tmp_path / "repo"
    repo.mkdir()
    learnings = repo / ".mergecraft" / "learnings.md"
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text(
        "# Learnings\n\n- keep timeouts on retry loops\n- drop this stale note\n",
        encoding="utf-8",
    )

    list_result = runner.invoke(app, ["memory", "list", "--repo", str(repo), "--json"])
    assert list_result.exit_code == 0, list_result.stdout
    listed = json.loads(list_result.stdout)["entries"]
    drop_id = next(entry["id"] for entry in listed if "drop this stale note" in entry["text"])

    forget_result = runner.invoke(app, ["memory", "forget", drop_id, "--repo", str(repo)])
    assert forget_result.exit_code == 0, forget_result.stdout

    remaining_text = learnings.read_text(encoding="utf-8")
    assert "drop this stale note" not in remaining_text
    assert "keep timeouts on retry loops" in remaining_text
    assert "## Active" not in remaining_text


def test_feedback_cli_records_outcome(tmp_path: Path) -> None:
    """``mergecraft memory feedback`` persists developer feedback by fingerprint."""
    from mergecraft.utils.memory import get_finding_feedback

    repo = tmp_path / "repo"
    repo.mkdir()
    fingerprint = "abc123fingerprint"

    result = runner.invoke(
        app,
        [
            "memory",
            "feedback",
            fingerprint,
            "--outcome",
            "dismissed",
            "--reason",
            "False positive on generated file",
            "--pr",
            "250",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.stdout

    record = get_finding_feedback(
        store_path=repo / ".mergecraft" / "feedback.json",
        fingerprint=fingerprint,
    )
    assert record is not None
    assert record.outcome.value == "dismissed"
    assert record.reason == "False positive on generated file"
    assert record.pr_number == 250
