"""Shared fixture helper for the root-gated analyzer UID-drop proofs.

Used by ``tests/security/test_analyzer_uid_drop.py`` and
``tests/analyzers/test_trusted_uid_drop.py`` (run as root by
``make test-uid-drop-privileged``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def make_traversable_for_dropped_uid(path: Path) -> None:
    """Add ``o+x`` to ``path`` and its ancestors so the dropped uid can traverse in.

    pytest's ``tmp_path`` lives under a root-owned ``0700`` base
    (``/tmp/pytest-of-<user>/pytest-<n>``), while the production analyzer
    workspace is traversable by the agent (``utils/privilege.prepare_workspace_for_agent``
    chowns it before the run). The sandbox correctly drops the payload to the
    agent uid; the fixture must then present a traversable parent chain or the
    payload cannot reach the ``1777`` tmpfs mounted at the scratch leaf. Grant
    traversal only — the leaf tmpfs stays world-writable and the real checkout
    stays unreadable. Stop at ``tempfile.gettempdir()`` and any ancestor that is
    already traversable by others.
    """
    stop = Path(tempfile.gettempdir()).resolve()
    current = path.resolve()
    while True:
        mode = current.stat().st_mode
        if mode & 0o001:
            break
        os.chmod(current, mode | 0o001)
        parent = current.parent
        if current == stop or parent == current:
            break
        current = parent
