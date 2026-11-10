"""Owner-only file creation for credential and harness config files.

Exports:
    Functions:
        write_private_file — create or replace a file whose mode is ``0600`` from creation.
    Constants:
        PRIVATE_FILE_MODE — the owner-only mode every such file is created with.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

PRIVATE_FILE_MODE: Final[int] = 0o600

_CREATE_FLAGS: Final[int] = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
)


def write_private_file(path: Path, text: str) -> None:
    """Write *text* to *path* so the file is owner-only from the moment it exists.

    The content goes to a fresh sibling created with ``O_CREAT | O_EXCL`` and mode
    ``0600``, then ``os.replace`` moves it over *path*. The file is never visible
    with a wider mode, an existing *path* (whatever its mode, owner or link target)
    is replaced rather than written through, and a reader never sees partial
    content. The parent directory must already exist.

    Args:
        path (Path): Destination file.
        text (str): UTF-8 content to write.

    Raises:
        OSError: When the sibling cannot be created, written or renamed; the
            sibling is removed first.
    """
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, _CREATE_FLAGS, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # A restrictive umask can only narrow the creation mode; pin it
            # exactly, before any content lands, so the owner can read it back.
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), PRIVATE_FILE_MODE)
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


__all__ = ["PRIVATE_FILE_MODE", "write_private_file"]
