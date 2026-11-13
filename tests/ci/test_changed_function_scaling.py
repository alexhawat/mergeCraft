"""Changed-function resolution parses each source once, regardless of hunk size."""

from __future__ import annotations

import ast
from unittest.mock import patch

from mergecraft.ci.changed_functions import changed_functions_from_diff


def test_large_changed_file_is_parsed_once() -> None:
    source = "".join(f"def function_{i}():\n    return {i}\n\n" for i in range(500))
    diff = "--- a/mod.py\n+++ b/mod.py\n@@ -1,1500 +1,1500 @@\n" + "".join(
        f"+{line}\n" for line in source.splitlines()
    )
    with patch("mergecraft.ci.changed_functions.ast.parse", wraps=ast.parse) as parse:
        symbols = changed_functions_from_diff(diff, {"mod.py": source})
    assert len(symbols) == 500
    assert [symbol.name for symbol in symbols] == [f"function_{i}" for i in range(500)]
    assert parse.call_count == 1
