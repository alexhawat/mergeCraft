import functools


class Foo:
    def bar(self, x):
        if x > 1:
            return 1
        if x > 2:
            return 2
        return 3


@functools.lru_cache
def top(x):
    if x:
        return 1
    return 0


def outer():
    def inner():
        return 1

    return inner()
