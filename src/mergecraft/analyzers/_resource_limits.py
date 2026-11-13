"""Apply analyzer resource limits in a fresh interpreter, then exec the payload.

Invoked by absolute filename with Python isolated mode: no checkout imports,
site customizations or Python environment variables can affect this launcher.
A limit failure exits before the payload runs.
"""

from __future__ import annotations

import os
import resource
import sys


def resource_limited_argv(
    argv: list[str], *, process_limit: tuple[int, int], memory_mb: int = 0
) -> list[str]:
    """Build a fresh-interpreter launcher for resolved child limits.

    Args:
        argv (list[str]): Command executed after limits are applied.
        process_limit (tuple[int, int]): Soft and hard process-count limits.
        memory_mb (int): Address-space limit, or zero to preserve the inherited limit.

    Returns:
        list[str]: Isolated Python invocation followed by limits and payload argv.
    """
    return [
        sys.executable,
        "-I",
        "-S",
        os.path.abspath(__file__),
        str(process_limit[0]),
        str(process_limit[1]),
        str(memory_mb),
        *argv,
    ]


def main() -> None:
    """Apply the parent's resolved limits and replace this process with its argv."""
    soft, hard, memory_mb = (int(value) for value in sys.argv[1:4])
    resource.setrlimit(resource.RLIMIT_NPROC, (soft, hard))
    if memory_mb > 0:
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    argv = sys.argv[4:]
    os.execvpe(argv[0], argv, os.environ)


if __name__ == "__main__":
    main()
