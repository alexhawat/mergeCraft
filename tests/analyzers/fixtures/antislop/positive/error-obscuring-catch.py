def lookup(key: str) -> str | None:
    try:
        return _fetch(key)
    except KeyError:
        return None
