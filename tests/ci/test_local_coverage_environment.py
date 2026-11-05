"""Local evidence executes in the discovered consumer tool's environment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

import pytest

from mergecraft.ci import local_evidence


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "logic.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    scratch = tmp_path / "coverage-output"
    scratch.mkdir()
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.setattr(local_evidence.tempfile, "mkdtemp", lambda **kwargs: str(scratch))
    # Sandbox construction has its own policy tests. Execute only this disposable
    # fixture so interpreter selection is tested with real processes on all OSes.
    monkeypatch.setattr(local_evidence, "_sandboxed_argv", lambda argv, **kwargs: argv)
    return root


def _assert_coverage(root: Path) -> None:
    artifact = local_evidence._execute_coverage(root, timeout_seconds=30)
    assert artifact is not None, "consumer tests did not produce coverage"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert 2 in payload["files"]["logic.py"]["executed_lines"]


def test_path_coverage_uses_separate_consumer_environment(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = tmp_path / "consumer-venv"
    venv.EnvBuilder(with_pip=False).create(consumer)
    scripts = consumer / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    site_result = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True,
        text=True,
        check=True,
    )
    consumer_site = Path(site_result.stdout.strip())
    # Reuse already provisioned packages, without pip/network or changing the
    # test runner's environment. This dependency exists only in the consumer.
    (consumer_site / "test-tools.pth").write_text(
        sysconfig.get_path("purelib") + "\n", encoding="utf-8"
    )
    (consumer_site / "consumer_only.py").write_text("VALUE = 42\n", encoding="utf-8")
    coverage = scripts / "coverage"
    coverage.write_text(
        f"#!{python}\nfrom coverage.cmdline import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    coverage.chmod(0o755)
    monkeypatch.setenv("PATH", str(scripts) + os.pathsep + os.defpath)
    (project / "test_logic.py").write_text(
        "import sys\nfrom pathlib import Path\nimport consumer_only\nfrom logic import answer\n"
        "def test_consumer_environment():\n"
        f"    assert Path(sys.prefix).resolve() == Path({str(consumer.resolve())!r})\n"
        "    assert answer() == consumer_only.VALUE\n",
        encoding="utf-8",
    )

    assert local_evidence._coverage_toolchain_available()
    _assert_coverage(project)


def test_module_fallback_when_no_path_executable_exists(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "")
    (project / "test_logic.py").write_text(
        "import sys\nfrom pathlib import Path\nfrom logic import answer\n"
        "def test_current_environment():\n"
        f"    assert Path(sys.prefix).resolve() == Path({str(Path(sys.prefix).resolve())!r})\n"
        "    assert answer() == 42\n",
        encoding="utf-8",
    )

    assert local_evidence._coverage_toolchain_available()
    _assert_coverage(project)
