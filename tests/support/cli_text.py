"""Width-stable CLI text helpers shared by CLI assertions (#1565).

Rich renders panels and soft-wraps long help text at the console width, so a
phrase an operator sees on one line can arrive split by a box-drawing border
(``│ a live │`` / ``│ agent │``) or by a plain newline. A test that asserts on
the phrase — not on the layout — normalises the captured stream through
:func:`compact_cli_text` so it passes at every ``COLUMNS`` value.
"""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Box-drawing block: light/heavy/double frame characters Rich panels use.
_BOX_DRAWING = re.compile(r"[\u2500-\u257f]")


def compact_cli_text(text: str) -> str:
    """Return *text* with styling and panel borders removed and space collapsed.

    ANSI escape sequences and every box-drawing character (``U+2500``-``U+257F``)
    are replaced first, so a phrase wrapped across a panel border becomes
    contiguous; the result then has runs of whitespace collapsed to one space
    and the ends trimmed. Casing is preserved for a caller that needs it.
    """
    plain = _ANSI.sub("", text)
    unbordered = _BOX_DRAWING.sub(" ", plain)
    return " ".join(unbordered.split())


__all__ = ["compact_cli_text"]
