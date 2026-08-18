"""DG7 memory lifecycle CLI verbs.

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG7).
Implementation: **DG7.2** — ``mergecraft memory list|show|forget|export|import``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
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


@pytest.mark.xfail(reason="green after DG7.2: memory lifecycle CLI", strict=False)
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
    listed = json.loads(list_result.stdout)
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
    remaining = json.loads(after_forget.stdout)
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
