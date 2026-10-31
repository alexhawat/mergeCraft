"""Path classifier for docs-only PR CI skips."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT


def _load_classifier():
    path = REPO_ROOT / "scripts" / "ci_pr_touches_code.py"
    spec = importlib.util.spec_from_file_location("ci_pr_touches_code_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_classifier = _load_classifier()
_matches_docs_only = _classifier._matches_docs_only
pr_touches_code = _classifier.pr_touches_code


def test_docs_only_markdown_and_docs_tree() -> None:
    changed = ["README.md", "docs/guide.md", "plans/008-coverage-shards.md"]
    assert pr_touches_code(changed) is False
    assert _matches_docs_only("CHANGELOG.md")
    assert not _matches_docs_only("evals/cases/foo.md")
    assert pr_touches_code(["evals/cases/foo.md"]) is True
    assert pr_touches_code([".github/skills/code-review/SKILL.md"]) is True
    assert not _matches_docs_only(".github/skills/code-review/SKILL.md")


def test_code_touch_in_src_or_workflows() -> None:
    assert pr_touches_code(["docs/x.md", "src/mergecraft/main.py"]) is True
    assert pr_touches_code([".github/workflows/ci.yml"]) is True
    assert pr_touches_code(["Makefile"]) is True
    assert pr_touches_code(["docs/diagrams/pipeline.d2"]) is True


def test_classifier_exits_zero_for_docs_only(tmp_path: Path) -> None:
    import subprocess

    repo = REPO_ROOT
    result = subprocess.run(
        [
            "python3",
            str(repo / "scripts" / "ci_pr_touches_code.py"),
            "--event",
            "pull_request",
            "--base",
            "main",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_empty_diff_is_not_code() -> None:
    assert pr_touches_code([]) is False
