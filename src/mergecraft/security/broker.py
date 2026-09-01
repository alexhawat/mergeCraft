"""Loopback credential broker for Codex model API calls (#553 option 3).

Exports:
    BROKER_BIND_HOST: Loopback bind address (D1).
    CODEX_BROKER_BEARER_ENV: Agent env var for the per-run throwaway bearer.
    CredentialBrokerBindError: Raised when bind host is not loopback.
    CredentialBrokerConfig: Upstream URL, API key, and per-run host allow-list.
    CredentialBrokerHandle: Running broker host, port, token, and base URL.
    CodexBrokerPosture: Whether the broker is active for this Codex run (D3a).
    broker_run_record_fields: Run-record disclosure fields (D3a/D10).
    credential_broker: Context manager that starts and stops the broker.
    redact_broker_output: Redact broker responses, errors, and logs (#553).
    resolve_codex_broker_posture: Subscription vs API-key posture (D3a).
    subscription_auth_usable: Whether ``CODEX_AUTH_JSON`` carries usable tokens.
"""

from __future__ import annotations

import json
import os
import posixpath
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.security.egress import (
    inspect_external_url,
    pinned_http_transport,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

BROKER_BIND_HOST = "127.0.0.1"
CODEX_BROKER_BEARER_ENV = "MERGECRAFT_CODEX_BROKER_TOKEN"
OPENAI_UPSTREAM_BASE_URL = "https://api.openai.com/v1"
OPENAI_UPSTREAM_HOST = "api.openai.com"

_MODEL_PATH_PREFIXES: tuple[str, ...] = (
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/models",
    "/v1/responses",
)

_MAX_BROKER_BODY_BYTES = 50 * 1024 * 1024

_HOST_SPOOF_HEADERS: tuple[str, ...] = ("Host", "X-Forwarded-Host")
_REDIRECT_STATUSES: frozenset[int] = frozenset(
    {
        HTTPStatus.MOVED_PERMANENTLY,
        HTTPStatus.FOUND,
        HTTPStatus.SEE_OTHER,
        HTTPStatus.TEMPORARY_REDIRECT,
        HTTPStatus.PERMANENT_REDIRECT,
    }
)


class CredentialBrokerBindError(ValueError):
    """Raised when the broker refuses a non-loopback bind address."""


@dataclass(frozen=True, slots=True)
class CredentialBrokerConfig:
    """Broker configuration for one Codex run."""

    upstream_base_url: str
    api_key: str
    run_upstream_hosts: frozenset[str]


@dataclass(frozen=True, slots=True)
class CredentialBrokerHandle:
    """A running loopback credential broker."""

    host: str
    port: int
    token: str
    base_url: str


@dataclass(frozen=True, slots=True)
class CodexBrokerPosture:
    """Whether the credential broker covers this Codex authentication mode."""

    active: bool
    auth_mode: str
    reason: str


def redact_broker_output(text: str) -> str:
    """Redact secret material from broker-facing text (#553)."""
    return redact_secrets(text)


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").casefold()


def subscription_auth_usable(raw: str) -> bool:
    """Return whether ``CODEX_AUTH_JSON`` carries usable subscription tokens."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        for key in ("access_token", "access", "refresh_token", "refresh"):
            val = tokens.get(key)
            if isinstance(val, str) and val.strip():
                return True
    for key in ("access_token", "access", "refresh_token", "refresh"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


# Backward-compatible alias — tests pin ``_subscription_auth_usable`` until renamed.
_subscription_auth_usable = subscription_auth_usable


def resolve_codex_broker_posture(*, openai_api_key: str = "") -> CodexBrokerPosture:
    """Return whether the broker is active for the current Codex auth mode (D3a)."""
    subscription_raw = os.environ.get("CODEX_AUTH_JSON", "").strip()
    if subscription_raw and subscription_auth_usable(subscription_raw):
        return CodexBrokerPosture(
            active=False,
            auth_mode="subscription",
            reason="broker inactive: subscription auth is not brokered",
        )
    api_key = openai_api_key.strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        return CodexBrokerPosture(
            active=True,
            auth_mode="api_key",
            reason="broker active for OpenAI API key auth",
        )
    return CodexBrokerPosture(
        active=False,
        auth_mode="none",
        reason="broker inactive: no OpenAI API key configured",
    )


def broker_run_record_fields(posture: CodexBrokerPosture) -> dict[str, str]:
    """Serialize broker posture for run-record disclosure (D3a/D10)."""
    return {
        "broker_active": str(posture.active).lower(),
        "broker_auth_mode": posture.auth_mode,
        "broker_reason": posture.reason,
    }


def _allowed_upstream_hosts(config: CredentialBrokerConfig) -> frozenset[str]:
    hosts = {_normalize_host(item) for item in config.run_upstream_hosts}
    hosts.add(_configured_upstream_host(config))
    return frozenset(hosts)


def _allowed_upstream_host(host: str, config: CredentialBrokerConfig) -> bool:
    return _normalize_host(host) in _allowed_upstream_hosts(config)


def _configured_upstream_host(config: CredentialBrokerConfig) -> str:
    parsed = urlparse(config.upstream_base_url)
    return _normalize_host(parsed.hostname or "")


def _normalized_request_path(path: str) -> str:
    bare = _request_path(path)
    if bare.startswith(("http://", "https://")):
        bare = urlparse(bare).path
    normalized = posixpath.normpath(bare)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _is_model_path(path: str) -> bool:
    normalized = _normalized_request_path(path)
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _MODEL_PATH_PREFIXES
    )


def _extract_bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    scheme, _, token = auth_header.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    return token.strip()


def _validate_bearer(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode(), expected.encode())


def _request_path(raw_path: str) -> str:
    if raw_path.startswith(("http://", "https://")):
        return urlparse(raw_path).path or "/"
    return raw_path.split("?", 1)[0]


def _absolute_request_url(raw_path: str) -> str | None:
    if raw_path.startswith(("http://", "https://")):
        return raw_path.split("?", 1)[0]
    return None


def _host_from_header(value: str) -> str:
    host = value.strip().split(",", 1)[0].strip()
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            return host[1:end]
    if ":" in host and not host.count(":") > 1:
        return host.rsplit(":", 1)[0]
    return host


def _broker_log(level: str, format: str, *args: object) -> None:
    redacted_args = tuple(redact_broker_output(str(arg)) for arg in args)
    getattr(logger, level)(redact_broker_output(format), *redacted_args)


def _upstream_request_path(request_path: str) -> str:
    path = _normalized_request_path(request_path)
    if path.startswith("/v1/"):
        return path[len("/v1") :]
    return path if path.startswith("/") else f"/{path}"


def _is_loopback_upstream_base_url(url: str) -> bool:
    """Return whether ``url`` targets a loopback host (test fixture upstreams only)."""
    host = _normalize_host(urlparse(url).hostname or "")
    return host in {"127.0.0.1", "localhost", "::1", "[::1]", "ip6-localhost", "ip6-loopback"}


def _upstream_client(config: CredentialBrokerConfig) -> httpx.Client:
    """Build the shared upstream client for one broker lifetime."""
    if _is_loopback_upstream_base_url(config.upstream_base_url):
        return httpx.Client(
            base_url=config.upstream_base_url,
            timeout=30.0,
            follow_redirects=False,
            verify=True,
        )
    guarded = inspect_external_url(config.upstream_base_url)
    transport = pinned_http_transport(
        guarded.host,
        guarded.addresses,
        verify=True,
    )
    return httpx.Client(
        transport=transport,
        base_url=config.upstream_base_url,
        timeout=30.0,
        follow_redirects=False,
        verify=True,
    )


def _redirect_host_allowed(location: str, config: CredentialBrokerConfig) -> bool:
    parsed = urlparse(location)
    host = parsed.hostname
    if not host:
        return False
    return _allowed_upstream_host(host, config)


def _error_response(status: HTTPStatus, detail: str) -> tuple[int, bytes, str]:
    body = redact_broker_output(json.dumps({"error": detail}))
    return status.value, body.encode(), "application/json"


@contextmanager
def credential_broker(
    config: CredentialBrokerConfig,
    *,
    bind_host: str | None = None,
) -> Iterator[CredentialBrokerHandle]:
    """Start a loopback broker; yield :class:`CredentialBrokerHandle`; stop on exit."""
    host = bind_host if bind_host is not None else BROKER_BIND_HOST
    if host != BROKER_BIND_HOST:
        msg = f"credential broker must bind loopback {BROKER_BIND_HOST!r}, not {host!r}"
        raise CredentialBrokerBindError(msg)

    token = secrets.token_urlsafe(32)
    configured_upstream_host = _configured_upstream_host(config)

    class _BrokerHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            _broker_log("debug", format, *args)

        def _read_body(self) -> bytes | None:
            raw_length = self.headers.get("Content-Length", "0") or "0"
            try:
                length = int(raw_length)
            except ValueError:
                self._reject(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
                return None
            if length < 0:
                self._reject(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
                return None
            if length == 0:
                return b""
            if length > _MAX_BROKER_BODY_BYTES:
                self._reject(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
                return None
            return self.rfile.read(length)

        def _reject(self, status: HTTPStatus, detail: str) -> None:
            code, body, content_type = _error_response(status, detail)
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def _validate_request(self) -> str | None:
            absolute_url = _absolute_request_url(self.path)
            if absolute_url is not None:
                parsed = urlparse(absolute_url)
                if parsed.hostname and not _allowed_upstream_host(parsed.hostname, config):
                    self._reject(HTTPStatus.FORBIDDEN, "absolute upstream URL not allow-listed")
                    return None

            for header_name in _HOST_SPOOF_HEADERS:
                header_value = self.headers.get(header_name)
                if not header_value:
                    continue
                spoof_host = _normalize_host(_host_from_header(header_value))
                if spoof_host in {_normalize_host(host), _normalize_host(BROKER_BIND_HOST)}:
                    continue
                if spoof_host == configured_upstream_host:
                    continue
                if not _allowed_upstream_host(spoof_host, config):
                    self._reject(HTTPStatus.FORBIDDEN, "upstream host header not allow-listed")
                    return None

            bearer = _extract_bearer(self.headers.get("Authorization"))
            if not _validate_bearer(bearer, token):
                self._reject(HTTPStatus.UNAUTHORIZED, "missing or invalid bearer token")
                return None

            path = _normalized_request_path(self.path)
            if not _is_model_path(path):
                self._reject(HTTPStatus.FORBIDDEN, "non-model path refused")
                return None

            return path

        def _proxy(self, method: str) -> None:
            path = self._validate_request()
            if path is None:
                return

            body = self._read_body()
            if body is None:
                return

            upstream_path = _normalized_request_path(self.path)

            forward_headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"authorization", "host", "content-length"}
            }
            forward_headers["Authorization"] = f"Bearer {config.api_key}"

            upstream_path = _upstream_request_path(upstream_path)
            try:
                with shared_upstream_client.stream(
                    method,
                    upstream_path,
                    content=body if body else None,
                    headers=forward_headers,
                ) as upstream_response:
                    if upstream_response.status_code in _REDIRECT_STATUSES:
                        location = upstream_response.headers.get("Location", "")
                        upstream_response.close()
                        if location and not _redirect_host_allowed(location, config):
                            self._reject(
                                HTTPStatus.FORBIDDEN,
                                "upstream redirect not allow-listed",
                            )
                            return
                        self._reject(HTTPStatus.BAD_GATEWAY, "upstream redirect refused")
                        return

                    response_body = upstream_response.read()
                    status_code = upstream_response.status_code
                    response_headers = dict(upstream_response.headers.items())
            except httpx.HTTPError as exc:
                _broker_log("warning", "broker upstream request failed: {}", exc)
                self._reject(HTTPStatus.BAD_GATEWAY, "upstream request failed")
                return

            if response_body:
                try:
                    text = response_body.decode()
                except UnicodeDecodeError:
                    redacted = redact_broker_output(response_body.decode("latin-1"))
                    if redacted.encode("latin-1") != response_body:
                        response_body = redacted.encode("latin-1")
                else:
                    redacted = redact_broker_output(text)
                    if redacted != text:
                        response_body = redacted.encode()

            self.send_response(status_code)
            for header, value in response_headers.items():
                lowered = header.lower()
                if lowered in {
                    "transfer-encoding",
                    "content-length",
                    "content-encoding",
                    "connection",
                }:
                    continue
                self.send_header(header, redact_broker_output(value))
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)
            self.close_connection = True

        def do_GET(self) -> None:
            self._proxy("GET")

        def do_POST(self) -> None:
            self._proxy("POST")

        def do_PUT(self) -> None:
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

        def do_DELETE(self) -> None:
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

        def do_PATCH(self) -> None:
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

        def do_OPTIONS(self) -> None:
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

    shared_upstream_client = _upstream_client(config)
    httpd = ThreadingHTTPServer((host, 0), _BrokerHandler)
    bound_port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    handle = CredentialBrokerHandle(
        host=host,
        port=bound_port,
        token=token,
        base_url=f"http://{host}:{bound_port}",
    )
    try:
        yield handle
    finally:
        shared_upstream_client.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            _broker_log("warning", "credential broker thread did not stop within 5s")
