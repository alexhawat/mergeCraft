"""Install a built wheel in isolation and run convergence outside the checkout."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """Fail if a built distribution cannot run its bundled convergence corpus."""
    wheel = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="mergecraft-wheel-") as temporary:
        root = Path(temporary)
        target = root / "installed"
        subprocess.run(
            [
                os.environ.get("UV", "uv"),
                "pip",
                "install",
                "--target",
                str(target),
                "--no-deps",
                str(wheel),
            ],
            check=True,
        )
        code = """import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import mergecraft
assert Path(mergecraft.__file__).is_relative_to(Path(sys.argv[1]))
from mergecraft.evals.convergence_benchmark import replay_convergence
result, path = replay_convergence(results_dir=Path('results'))
assert result.convergence is not None and result.convergence.cases_total > 0
assert path.is_file()
print('installed wheel convergence passed')
"""
        subprocess.run([sys.executable, "-I", "-c", code, str(target)], cwd=root, check=True)


if __name__ == "__main__":
    main()
