"""Loopback proxy that injects curated OpenAI generation caps into outbound requests (#983)."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from mergecraft.security.broker import BROKER_BIND_HOST
from mergecraft.security.egress import inspect_external_url, pinned_http_transport

if TYPE_CHECKING:
    from collections.abc import Iterator

_MAX_BODY_BYTES = 50 * 1024 * 1024
_MODEL_PREFIXES = (
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/responses",
)


@dataclass(frozen=True, slots=True)
class OpenAIGenerationProxyHandle:
    """Running loopback proxy for one OpenAI-compatible upstream."""

    provider_id: str
    upstream_base_url: str
    host: str
    port: int
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"


def _normalize_path(path: str) -> str:
    bare = path.split("?", 1)[0]
    if bare.startswith(("http://", "https://")):
        bare = urlparse(bare).path or "/"
    return bare if bare.startswith("/") else f"/{bare}"


def _is_model_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in _MODEL_PREFIXES
    )


def merge_generation_into_request_body(
    body: bytes,
    *,
    path: str,
    provider_id: str,
    default_model_slug: str | None,
) -> bytes:
    """Apply catalog generation defaults to a chat/responses JSON body."""
    if not body or not _is_model_path(path):
        return body
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    if not isinstance(payload, dict):
        return body

    from mergecraft.agents.openai_compatible_gateways import _provider_config_for_model
    from mergecraft.agents.openai_generation_params import (
        openai_chat_completion_body_fields,
        openai_responses_body_fields,
    )

    model_field = payload.get("model")
    slug = default_model_slug
    if isinstance(model_field, str) and model_field.strip():
        raw = model_field.strip()
        slug = raw if "/" in raw else f"{provider_id}/{raw}"
    if not slug:
        return body

    provider_config = _provider_config_for_model(slug)
    extra = dict(provider_config.extra_options) if provider_config is not None else {}
    normalized_path = _normalize_path(path)
    if normalized_path.startswith("/v1/responses"):
        fields = openai_responses_body_fields(slug, extra)
    else:
        fields = openai_chat_completion_body_fields(slug, extra)
    if not fields:
        return body
    merged = dict(payload)
    for key, value in fields.items():
        merged.setdefault(key, value)
    return json.dumps(merged).encode()


@contextmanager
def openai_generation_proxy(
    *,
    provider_id: str,
    upstream_base_url: str,
    default_model_slug: str | None,
) -> Iterator[OpenAIGenerationProxyHandle]:
    """Start a loopback proxy; rewrite Codex ``base_url`` to :attr:`base_url`."""
    guarded = inspect_external_url(upstream_base_url.rstrip("/"))
    transport = pinned_http_transport(guarded.host, guarded.addresses, verify=True)
    upstream_client = httpx.Client(
        transport=transport,
        base_url=upstream_base_url.rstrip("/"),
        timeout=httpx.Timeout(1500.0),
        follow_redirects=False,
        verify=True,
    )

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _reject(self, status: HTTPStatus, detail: str) -> None:
            body = json.dumps({"error": detail}).encode()
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self, method: str) -> None:
            path = _normalize_path(self.path)
            if not _is_model_path(path):
                self._reject(HTTPStatus.FORBIDDEN, "non-model path refused")
                return
            raw_length = self.headers.get("Content-Length", "0") or "0"
            try:
                length = int(raw_length)
            except ValueError:
                self._reject(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
                return
            body = self.rfile.read(length) if length > 0 else b""
            if length > _MAX_BODY_BYTES:
                self._reject(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
                return
            body = merge_generation_into_request_body(
                body,
                path=path,
                provider_id=provider_id,
                default_model_slug=default_model_slug,
            )
            forward_headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "content-length"}
            }
            upstream_path = path[len("/v1") :] if path.startswith("/v1/") else path
            response = upstream_client.request(
                method,
                upstream_path,
                content=body or None,
                headers=forward_headers,
            )
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() in {"transfer-encoding", "content-encoding", "connection"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.content)

        def do_POST(self) -> None:
            self._proxy("POST")

        def do_GET(self) -> None:
            self._proxy("GET")

    server = ThreadingHTTPServer((BROKER_BIND_HOST, 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    handle = OpenAIGenerationProxyHandle(
        provider_id=provider_id,
        upstream_base_url=upstream_base_url.rstrip("/"),
        host=BROKER_BIND_HOST,
        port=int(server.server_address[1]),
    )
    try:
        yield handle
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        upstream_client.close()


__all__ = [
    "OpenAIGenerationProxyHandle",
    "merge_generation_into_request_body",
    "openai_generation_proxy",
]
