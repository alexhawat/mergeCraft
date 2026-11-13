"""Apply analyzer resource limits in a fresh interpreter, then exec the payload.

Invoked by absolute filename with Python isolated mode: no checkout imports,
site customizations or Python environment variables can affect this launcher.
A limit failure exits before the payload runs.
"""

from __future__ import annotations

import os
import resource
import sys


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
