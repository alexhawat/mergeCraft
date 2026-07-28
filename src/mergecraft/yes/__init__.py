"""Async retry primitive (ported from mergecraft ``yes/op``)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar, overload

from loguru import logger

P = ParamSpec("P")
R = TypeVar("R")

AnyAsyncFn = Callable[..., Awaitable[Any]]
BailFn = Callable[[BaseException], bool]
RetryAfterFn = Callable[[BaseException], float | None]

DEFAULT_RETRY_AFTER_CAP_MS = 20_000
_VOID_KEY = "~void"


def _cache_key(value: Any) -> str:
    if value is None:
        msg = "cache key cannot be null"
        raise ValueError(msg)
    if value is ...:  # pragma: no cover - sentinel unused
        return _VOID_KEY
    if isinstance(value, str):
        return value
    try:
        payload = json.dumps(value, sort_keys=True, default=str)
    except TypeError as exc:
        msg = f"cache key cannot be hashed: {exc}"
        raise ValueError(msg) from exc
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def retry_after_ms(error: BaseException) -> float | None:
    """Extract Retry-After / rate-limit reset delay from an HTTP-ish error."""
    response = getattr(error, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
    if isinstance(retry_after, str) and retry_after.strip():
        try:
            seconds = float(retry_after)
            if seconds == seconds:  # not NaN
                return max(0.0, seconds * 1000)
        except ValueError:
            pass
        try:
            from email.utils import parsedate_to_datetime

            date_ms = parsedate_to_datetime(retry_after).timestamp() * 1000
            return max(0.0, date_ms - time.time() * 1000)
        except TypeError, ValueError, OverflowError:
            pass
    remaining = headers.get("x-ratelimit-remaining") if hasattr(headers, "get") else None
    if remaining == "0":
        reset = headers.get("x-ratelimit-reset") if hasattr(headers, "get") else None
        if isinstance(reset, str) and reset.strip():
            try:
                reset_epoch = float(reset)
                return max(0.0, reset_epoch * 1000 - time.time() * 1000)
            except ValueError:
                pass
    return None


@dataclass
class OpOptions:
    name: str | None = None
    ttl: float | None = None
    max_items: int = 1000
    retries: list[float] | None = None
    retry_after: bool | RetryAfterFn | None = None
    retry_after_cap: float = DEFAULT_RETRY_AFTER_CAP_MS
    bail: BailFn | None = None
    skip_cache: Callable[[Any], bool] | None = None


class OpFunction:
    """Callable wrapper with optional LRU cache + retry schedule."""

    def __init__(self, fn: AnyAsyncFn, options: OpOptions) -> None:
        self._fn = fn
        self._options = options
        self._cache: dict[str, Any] = {}
        self._key_map: dict[str, Any] = {}
        self._in_flight: dict[str, asyncio.Future[Any]] = {}
        self._accepts_ctx = fn.__code__.co_argcount >= 2

    def clear(self, key: Any = None) -> None:
        if self._options.ttl is None:
            return
        if key is None:
            self._cache.clear()
            self._key_map.clear()
            return
        string_key = _cache_key(key)
        self._cache.pop(string_key, None)
        self._key_map.pop(string_key, None)

    def has(self, key: Any) -> bool:
        if self._options.ttl is None:
            return False
        return _cache_key(key) in self._cache

    def invalidate(self, predicate: Callable[[Any], bool]) -> int:
        if self._options.ttl is None:
            return 0
        count = 0
        for string_key, original in list(self._key_map.items()):
            if predicate(original):
                self._cache.pop(string_key, None)
                self._key_map.pop(string_key, None)
                count += 1
        return count

    async def __call__(self, input: Any = None, ctx: Any = None) -> Any:
        options = self._options
        name_prefix = f"[{options.name}] " if options.name else ""
        key = _cache_key(input) if input is not None else _VOID_KEY
        should_cache = options.ttl is not None

        if should_cache and key in self._cache:
            return self._cache[key]

        in_flight = self._in_flight.get(key)
        if in_flight is not None:
            return await in_flight

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._in_flight[key] = future

        retries = options.retries or []
        last_error: BaseException | None = None

        try:
            for attempt in range(len(retries) + 1):
                try:
                    result = (
                        await self._fn(input, ctx) if self._accepts_ctx else await self._fn(input)
                    )
                    skip = options.skip_cache(result) if options.skip_cache else False
                    if should_cache and result is not None and not skip:
                        self._cache[key] = result
                        self._key_map[key] = input
                    future.set_result(result)
                    return result
                except BaseException as error:
                    if options.bail and options.bail(error):
                        future.set_exception(error)
                        raise
                    last_error = error
                    is_last = attempt >= len(retries)
                    if is_last:
                        logger.info(
                            "{}attempt {}/{} failed, no more retries",
                            name_prefix,
                            attempt + 1,
                            len(retries) + 1,
                        )
                        break
                    delay_ms = retries[attempt]
                    if options.retry_after:
                        extract = (
                            retry_after_ms if options.retry_after is True else options.retry_after
                        )
                        hint = extract(error)
                        if hint is not None:
                            delay_ms = max(delay_ms, min(options.retry_after_cap, hint))
                    logger.info(
                        "{}attempt {}/{} failed, retrying in {}ms",
                        name_prefix,
                        attempt + 1,
                        len(retries) + 1,
                        delay_ms,
                    )
                    await asyncio.sleep(delay_ms / 1000.0)

            assert last_error is not None
            future.set_exception(last_error)
            raise last_error
        finally:
            self._in_flight.pop(key, None)


@overload
def op(
    fn: Callable[P, Awaitable[R]],
    options: OpOptions | None = None,
) -> OpFunction: ...


@overload
def op(
    fn: None = None,
    *,
    name: str | None = None,
    retries: list[float] | None = None,
    bail: BailFn | None = None,
    ttl: float | None = None,
    retry_after: bool | RetryAfterFn | None = None,
    retry_after_cap: float = DEFAULT_RETRY_AFTER_CAP_MS,
) -> Callable[[Callable[P, Awaitable[R]]], OpFunction]: ...


def op(
    fn: AnyAsyncFn | None = None,
    options: OpOptions | dict[str, Any] | None = None,
    *,
    name: str | None = None,
    retries: list[float] | None = None,
    bail: BailFn | None = None,
    ttl: float | None = None,
    retry_after: bool | RetryAfterFn | None = None,
    retry_after_cap: float = DEFAULT_RETRY_AFTER_CAP_MS,
) -> OpFunction | Callable[[AnyAsyncFn], OpFunction]:
    """Wrap an async function with retries (and optional cache).

    Usage mirrors upstream ``yes.op(fn, { retries, bail })``.
    """

    def _build(target: AnyAsyncFn, opts: OpOptions) -> OpFunction:
        return OpFunction(target, opts)

    if isinstance(options, dict):
        opts = OpOptions(
            name=options.get("name", name),
            ttl=options.get("ttl", ttl),
            retries=options.get("retries", retries),
            bail=options.get("bail", bail),
            retry_after=options.get("retry_after", options.get("retryAfter", retry_after)),
            retry_after_cap=float(
                options.get("retry_after_cap") or options.get("retryAfterCap") or retry_after_cap
            ),
            skip_cache=options.get("skip_cache", options.get("skipCache")),
        )
    elif isinstance(options, OpOptions):
        opts = options
    else:
        opts = OpOptions(
            name=name,
            ttl=ttl,
            retries=retries,
            bail=bail,
            retry_after=retry_after,
            retry_after_cap=retry_after_cap,
        )

    if fn is None:

        def decorator(target: AnyAsyncFn) -> OpFunction:
            return _build(target, opts)

        return decorator

    return _build(fn, opts)


def range_n(n: int) -> list[int]:
    return list(range(n))


__all__ = [
    "DEFAULT_RETRY_AFTER_CAP_MS",
    "OpFunction",
    "OpOptions",
    "op",
    "range_n",
    "retry_after_ms",
]
