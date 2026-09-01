"""W5 — workflow_lint.sh emits parseable actionlint SARIF on clean workflows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT

_ACTIONLINT_TEMPLATE = (
    REPO_ROOT / "src" / "mergecraft" / "analyzers" / "catalog" / "actionlint-sarif-template.txt"
)


def test_workflow_lint_script_uses_catalog_actionlint_sarif_template() -> None:
    """SARIF mode must use the catalog Go template — actionlint has no named ``sarif`` format."""
    script = (REPO_ROOT / "scripts" / "workflow_lint.sh").read_text(encoding="utf-8")
    assert "ACTIONLINT_SARIF_TEMPLATE=" in script
    assert "actionlint-sarif-template.txt" in script
    assert '-format "${ACTIONLINT_SARIF_TEMPLATE}"' in script
    assert _ACTIONLINT_TEMPLATE.is_file()


@pytest.mark.skipif(
    sys.platform != "linux", reason="actionlint bootstrap is linux-only in workflow_lint.sh"
)
def test_workflow_lint_emits_parseable_actionlint_sarif(tmp_path: Path) -> None:
    """Clean workflows produce SARIF 2.1.0 the ciEvidence ingest path can parse."""
    env = os.environ.copy()
    env["MERGECRAFT_WORKFLOW_SARIF_DIR"] = str(tmp_path)
    completed = subprocess.run(
        ["./scripts/workflow_lint.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    out = tmp_path / "actionlint.sarif"
    assert out.is_file()
    assert out.stat().st_size > 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("version") == "2.1.0"
    assert payload.get("runs")
