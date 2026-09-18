def load_config(raw: dict[str, object] | None) -> dict[str, object]:
    """Return config; optional nested key is intentionally unchecked."""
    return raw or {}
