"""RV1.5 — runnable CLI example trees (RED until RV5).

Pins complete ``examples/cli/**`` trees, offline ``run.sh`` checks, expected-output
fixtures, manifest exclusions, and the landing README CLI how-it-works section.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text

EXAMPLES_CLI = REPO_ROOT / "examples" / "cli"
CLI_EXAMPLES_DOC = REPO_ROOT / "docs" / "cli-examples.md"
MANIFEST = REPO_ROOT / "docs" / "manifest.yaml"
README = REPO_ROOT / "README.md"

_CLI_SECTION_RE = re.compile(
    r"^##\s+How it works.*CLI[^\n]*",
    re.MULTILINE | re.IGNORECASE,
)


def _example_dirs() -> list[Path]:
    if not EXAMPLES_CLI.is_dir():
        return []
    return sorted(path for path in EXAMPLES_CLI.iterdir() if path.is_dir())


def _manifest_paths() -> set[str]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    pages = data.get("pages") or []
    paths: set[str] = set()
    for row in pages:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            paths.add(row["path"])
    return paths


def _run_script_is_executable(path: Path) -> bool:
    mode = path.stat().st_mode
    return bool(mode & stat.S_IXUSR)


def test_every_example_tree_is_complete() -> None:
    dirs = _example_dirs()
    assert dirs, f"missing example trees under {EXAMPLES_CLI.relative_to(REPO_ROOT)}"
    incomplete: list[str] = []
    for example_dir in dirs:
        name = example_dir.name
        if not (example_dir / "README.md").is_file():
            incomplete.append(f"{name}: README.md")
        run_sh = example_dir / "run.sh"
        if not run_sh.is_file() or not _run_script_is_executable(run_sh):
            incomplete.append(f"{name}: run.sh (executable)")
        if not (example_dir / ".mergecraft" / "config.yaml").is_file():
            incomplete.append(f"{name}: .mergecraft/config.yaml")
        review_files = [
            p
            for p in example_dir.rglob("*")
            if p.is_file()
            and p.name not in {"README.md", "run.sh"}
            and ".mergecraft" not in p.parts
            and "expected" not in p.parts
        ]
        if not review_files:
            incomplete.append(f"{name}: no files under review")
    assert not incomplete, "incomplete CLI example trees:\n" + "\n".join(incomplete)


def test_run_sh_is_offline() -> None:
    dirs = _example_dirs()
    assert dirs, f"missing example trees under {EXAMPLES_CLI.relative_to(REPO_ROOT)}"
    offenders: list[str] = []
    for example_dir in dirs:
        run_sh = example_dir / "run.sh"
        if not run_sh.is_file():
            offenders.append(f"{example_dir.name}: missing run.sh")
            continue
        text = run_sh.read_text(encoding="utf-8")
        if "--dry-run" not in text and "EXIT" not in text.upper():
            offenders.append(example_dir.name)
    assert not offenders, (
        f"run.sh must use --dry-run or assert a documented exit code (D12): {offenders}"
    )


def test_expected_output_fixtures_match() -> None:
    dirs = _example_dirs()
    assert dirs, f"missing example trees under {EXAMPLES_CLI.relative_to(REPO_ROOT)}"
    for example_dir in dirs:
        run_sh = example_dir / "run.sh"
        expected_dir = example_dir / "expected"
        if not run_sh.is_file() or not expected_dir.is_dir():
            continue
        proc = subprocess.run(
            ["bash", str(run_sh)],
            cwd=example_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"{example_dir.name}/run.sh failed: {proc.stderr or proc.stdout}"
        )
        for fixture in expected_dir.iterdir():
            if not fixture.is_file():
                continue
            produced = example_dir / fixture.name
            assert produced.is_file(), f"{example_dir.name}: missing output {fixture.name}"
            assert produced.read_bytes() == fixture.read_bytes(), (
                f"{example_dir.name}: drift in {fixture.name}"
            )


def test_examples_are_not_manifested() -> None:
    paths = _manifest_paths()
    manifested_examples = sorted(path for path in paths if path.startswith("examples/cli/"))
    assert not manifested_examples, (
        f"examples/cli/** must stay out of docs/manifest.yaml (D10): {manifested_examples}"
    )
    assert "docs/cli-examples.md" in paths, "docs/manifest.yaml must list docs/cli-examples.md"


def test_landing_has_cli_section() -> None:
    text = read_text("README.md")
    assert _CLI_SECTION_RE.search(text), (
        "README needs ## How it works — CLI (or similar) section (A7)"
    )
    assert "docs/cli-examples.md" in text, "README CLI section must link docs/cli-examples.md"
