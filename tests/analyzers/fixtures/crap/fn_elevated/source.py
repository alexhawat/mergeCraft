def fn_elevated(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return 2
    if value == 0:
        return 3
    return 0
