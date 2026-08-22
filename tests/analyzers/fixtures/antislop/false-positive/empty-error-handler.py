def load() -> str:
    try:
        return open("data.txt", encoding="utf-8").read()
    except OSError as exc:
        raise RuntimeError("load failed") from exc
