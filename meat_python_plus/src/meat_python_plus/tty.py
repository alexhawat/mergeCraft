"""TTY detection matching Go meat ``cmd/meat/isatty_*.go`` + ``isTerminal``.

Uses Python ``os.isatty`` (portable equivalent of isatty(3)) so redirects to
regular files and ``/dev/null`` stay non-interactive — same contract as git.
"""

from __future__ import annotations

import io
import os
from typing import Any


def is_terminal(stream: Any) -> bool:
    """Return True when *stream* refers to an interactive terminal.

    Non-file writers (``StringIO``, builders) and streams whose ``fileno()`` is
    unsupported are never terminals. Regular files and ``/dev/null`` also
    return False because ``os.isatty`` probes the real fd.
    """
    fileno = getattr(stream, "fileno", None)
    if fileno is None or not callable(fileno):
        return False
    try:
        fd = fileno()
    except (OSError, ValueError, io.UnsupportedOperation, AttributeError):
        return False
    try:
        return os.isatty(int(fd))
    except (OSError, TypeError, ValueError):
        return False
