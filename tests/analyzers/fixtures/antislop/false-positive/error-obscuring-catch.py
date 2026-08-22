def lookup(key: str) -> str:
    try:
        return _fetch(key)
    except KeyError as exc:
        raise ValueError(f"missing key: {key}") from exc
