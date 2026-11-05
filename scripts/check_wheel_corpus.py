"""Exercise a built wheel and its CLI using only its declared runtime dependencies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """Install into a fresh venv and run offline acceptance outside the checkout."""
    wheel = Path(sys.argv[1]).resolve()
    uv = os.environ.get("UV", "uv")
    with tempfile.TemporaryDirectory(prefix="mergecraft-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
            and not key.startswith(("MERGECRAFT_", "INPUT_", "GITHUB_"))
        }
        env["HOME"] = str(root)
        subprocess.run(
            [uv, "venv", "--python", sys.executable, str(environment)],
            cwd=root,
            env=env,
            check=True,
        )
        binary_dir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binary_dir / ("python.exe" if os.name == "nt" else "python")
        cli = binary_dir / ("mergecraft.exe" if os.name == "nt" else "mergecraft")
        # Resolve only the wheel's metadata: no dev extras, editable checkout or
        # --no-deps shortcut that could hide a missing dependency declaration.
        subprocess.run(
            [uv, "pip", "install", "--python", str(python), str(wheel)],
            cwd=root,
            env=env,
            check=True,
        )
        code = """import importlib.util, sys
from pathlib import Path
import mergecraft
assert Path(mergecraft.__file__).is_relative_to(Path(sys.prefix))
assert importlib.util.find_spec('pytest') is None
from mergecraft.evals.convergence_benchmark import replay_convergence
result, path = replay_convergence(results_dir=Path('results'))
assert result.convergence is not None and result.convergence.cases_total > 0
assert path.is_file()
print('installed wheel convergence passed')
"""
        subprocess.run([str(python), "-I", "-c", code], cwd=root, env=env, check=True)
        for args in (["--help"], ["eval", "--help"], ["config", "validate"], ["--version"]):
            subprocess.run([str(cli), *args], cwd=root, env=env, check=True)
        result = subprocess.run(
            [str(cli), "--format", "json", "capabilities"],
            cwd=root,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        assert json.loads(result.stdout)["review_only"] is True
        print("installed wheel CLI acceptance passed")


if __name__ == "__main__":
    main()
