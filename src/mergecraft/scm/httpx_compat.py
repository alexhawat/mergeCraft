"""Optional httpx compatibility hooks for webhook ingress tests.

Production FastAPI receives raw HTTP header bytes; Starlette ``TestClient`` builds
requests through httpx, which rejects non-ASCII header values unless normalized
as latin-1. Call :func:`install_httpx_latin1_header_values` from test conftest
before exercising webhook routes through ``TestClient``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    class _HttpxModelsLatin1Patch:
        _normalize_header_value: Callable[[str | bytes, str | None], bytes]
        _mergecraft_latin1_patched: bool


def install_httpx_latin1_header_values() -> None:
    """Match HTTP latin-1 header bytes when httpx builds TestClient requests."""
    import importlib

    for module_name in ("httpx._models", "httpx2._models"):
        try:
            httpx_models = importlib.import_module(module_name)
        except ImportError:
            continue
        if getattr(httpx_models, "_mergecraft_latin1_patched", False):
            continue

        def normalize(value: str | bytes, encoding: str | None = None) -> bytes:
            if isinstance(value, bytes):
                return value
            if not isinstance(value, str):
                msg = f"Header value must be str or bytes, not {type(value)}"
                raise TypeError(msg)
            if encoding is not None:
                return value.encode(encoding)
            try:
                return value.encode("ascii")
            except UnicodeEncodeError:
                return value.encode("latin-1")

        models = cast(  # importlib ModuleType lacks httpx private attrs
            "_HttpxModelsLatin1Patch", httpx_models
        )
        models._normalize_header_value = normalize
        models._mergecraft_latin1_patched = True


__all__ = ["install_httpx_latin1_header_values"]
