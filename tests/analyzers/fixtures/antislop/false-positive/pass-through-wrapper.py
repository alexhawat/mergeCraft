def helper(value: int) -> int:
    return value * 2


def wrapper(value: int) -> int:
    return helper(value) + 1
