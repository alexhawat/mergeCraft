"""Example drift checks must not rewrite tracked outputs."""

from pathlib import Path

from scripts import check_cli_examples as examples


def test_check_runs_in_copy_and_preserves_original(tmp_path: Path) -> None:
    fixture = tmp_path / "example"
    fixture.mkdir()
    (fixture / "expected").mkdir()
    (fixture / "expected" / "result.txt").write_text("new\n")
    (fixture / "result.txt").write_text("old tracked output\n")
    (fixture / "run.sh").write_text("#!/bin/bash\nprintf 'new\\n' > result.txt\n")
    assert examples.check_example(fixture) == []
    assert (fixture / "result.txt").read_text() == "old tracked output\n"


def test_existing_output_cannot_hide_a_missing_generated_file(tmp_path: Path) -> None:
    fixture = tmp_path / "example"
    fixture.mkdir()
    (fixture / "expected").mkdir()
    (fixture / "expected" / "result.txt").write_text("old\n")
    (fixture / "result.txt").write_text("old\n")
    (fixture / "run.sh").write_text("#!/bin/bash\nexit 0\n")
    assert "missing output" in examples.check_example(fixture)[0]
