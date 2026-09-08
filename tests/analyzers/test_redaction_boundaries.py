"""Independent punctuation and source-path redaction regressions."""

from mergecraft.analyzers.redact import redact_secrets


def test_assignment_preserves_closing_bracket() -> None:
    output = redact_secrets("found [password=public-fixture-value] here")
    assert "public-fixture-value" not in output
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
