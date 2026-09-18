def fn_watch(value: int) -> int:
    if value > 0:
        return 1
    if value < -10:
        return 2
    if value == -5:
        return 3
    if value == -1:
        return 4
    return 0
