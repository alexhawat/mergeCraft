"""Independent punctuation and source-path redaction regressions."""

import pytest

from mergecraft.analyzers.redact import redact_secrets


def test_assignment_preserves_closing_bracket() -> None:
    output = redact_secrets("found [password=public-fixture-value] here")
    assert "public-fixture-value" not in output
    assert output.endswith("] here")


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_assignment_does_not_expose_secret_after_interior_bracket(quote: str) -> None:
    output = redact_secrets(f"found [password={quote}abcdefgh]private_tail{quote}] here")
    assert "abcdefgh" not in output
    assert "private_tail" not in output
    assert output.endswith("] here")


def test_source_path_remains_readable() -> None:
    path = "src/mergecraft/analyzers/redact.py"
    assert redact_secrets(path) == path
    assert redact_secrets(f"changed {path} today") == f"changed {path} today"


def test_secret_inside_source_path_is_still_redacted() -> None:
    secret = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"
    assert secret not in redact_secrets(f"src/{secret}/redact.py")
    dense = "Q8nV4zK7pR2wX6mJ9sT3bF5h"
    assert dense not in redact_secrets(f"src/{dense}/redact.py")
