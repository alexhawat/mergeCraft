"""Replace a file atomically: write a sibling temp file, then ``os.replace`` it.

A reader, or the next run after an interrupted write, sees either the old
content or the new content, never a truncated file. The temp file is removed
when the write fails.

Exports:
    write_bytes_atomically: Replace a file with bytes.
    write_text_atomically: Replace a file with UTF-8 text.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_bytes_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` via a sibling temp file and an atomic rename.

    Args:
        path: Destination file. Its parent directory must exist.
        data: The complete new content.

    Raises:
        OSError: The temp file could not be written or renamed; ``path`` is unchanged.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_text_atomically(path: Path, text: str) -> None:
    """Replace ``path`` with UTF-8 ``text`` atomically (see :func:`write_bytes_atomically`)."""
    write_bytes_atomically(path, text.encode("utf-8"))


__all__ = ["write_bytes_atomically", "write_text_atomically"]
