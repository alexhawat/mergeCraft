"""Local OpenAI-compatible HTTP stub for provider-harness tests."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.diagnostics import format_mismatch
from tests.support.provider_harness.matcher import (
    AmbiguousFixtureMatch,
    FixtureReuseError,
    NoFixtureMatch,
    match_fixture,
)
from tests.support.provider_harness.metrics import HarnessMetrics
from tests.support.provider_harness.profiles import apply_profile
from tests.support.provider_harness.recorder import write_record
from tests.support.provider_harness.redaction import sanitize_json_text
from tests.support.provider_harness.schema import FixtureSpec, load_fixture_file

_HISTORY_CAP = 32


@dataclass
class RedactedRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: str


def _chat_completion_from_fixture(fixture: FixtureSpec) -> dict[str, Any]:
    if fixture.response.body is not None and isinstance(fixture.response.body, dict):
        payload = dict(fixture.response.body)
        if fixture.response.usage:
            payload["usage"] = fixture.response.usage
        if fixture.response.request_id:
            payload["id"] = fixture.response.request_id
        if fixture.response.finish_reason and payload.get("choices"):
            payload["choices"][0]["finish_reason"] = fixture.response.finish_reason
        return payload
    text_parts = [block.text or "" for block in fixture.response.blocks if block.kind == "text"]
    content = "".join(text_parts) if text_parts else "{}"
    payload: dict[str, Any] = {
        "id": fixture.response.request_id or "chatcmpl-stub",
        "object": "chat.completion",
        "model": fixture.match.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": fixture.response.finish_reason or "stop",
            }
        ],
    }
    if fixture.response.usage:
        payload["usage"] = fixture.response.usage
    return payload


def _sse_chunks(fixture: FixtureSpec) -> list[str]:
    chunks: list[str] = []
    if fixture.response.blocks:
        for block in fixture.response.blocks:
            if block.kind == "text" and block.text:
                data = {"choices": [{"delta": {"content": block.text}, "index": 0}]}
                chunks.append(f"data: {json.dumps(data)}\n\n")
            if fixture.response.delay_ms:
                time.sleep(fixture.response.delay_ms / 1000.0)
    elif isinstance(fixture.response.body, dict):
        choices = fixture.response.body.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        data = {"choices": [{"delta": {"content": content}, "index": 0}]}
        chunks.append(f"data: {json.dumps(data)}\n\n")
    chunks.append("data: [DONE]\n\n")
    return chunks


class ProviderHarnessServer:
    def __init__(self, fixtures: list[FixtureSpec] | None = None) -> None:
        self._fixtures = list(fixtures or [])
        self._history: list[RedactedRequest] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._host = "127.0.0.1"
        self._port = 0
        self._usage_counts: dict[str, int] = {}
        self.metrics = HarnessMetrics()

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("server not started")
        return f"http://{self._host}:{self._port}/v1"

    @property
    def origin(self) -> str:
        if self._httpd is None:
            raise RuntimeError("server not started")
        return f"http://{self._host}:{self._port}"

    @property
    def history(self) -> list[RedactedRequest]:
        with self._lock:
            return list(self._history)

    def reload(self, fixtures: list[FixtureSpec] | None = None) -> None:
        with self._lock:
            if fixtures is not None:
                self._fixtures = list(fixtures)
            self._usage_counts.clear()
            self.metrics.reset()

    def url_for(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.origin + path

    def start(self) -> None:
        if self._httpd is not None:
            return
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def _send_bytes(
                self, status: int, body: bytes, headers: dict[str, str] | None = None
            ) -> None:
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                if "Content-Type" not in (headers or {}):
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(
                self, status: int, payload: object, headers: dict[str, str] | None = None
            ) -> None:
                self._send_bytes(status, json.dumps(payload).encode("utf-8"), headers)

            def _authorized(self) -> bool:
                return self.headers.get("Authorization", "") == f"Bearer {DUMMY_API_KEY}"

            def _record(self, body_bytes: bytes) -> None:
                redacted = sanitize_json_text(body_bytes.decode("utf-8", errors="replace"))
                entry = RedactedRequest(
                    method=self.command,
                    path=urlparse(self.path).path,
                    headers={
                        "Authorization": "[REDACTED]" if self.headers.get("Authorization") else ""
                    },
                    body=redacted[:2048],
                )
                with server_ref._lock:
                    server_ref._history.append(entry)
                    if len(server_ref._history) > _HISTORY_CAP:
                        del server_ref._history[:-_HISTORY_CAP]

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path in {"/health", "/ready"}:
                    self._send_json(HTTPStatus.OK, {"status": "ok"})
                    return
                if path == "/v1/models":
                    if not self._authorized():
                        self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_api_key"})
                        return
                    self._record(b"")
                    self._send_json(
                        HTTPStatus.OK,
                        {"object": "list", "data": [{"id": "dummy", "object": "model"}]},
                    )
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_POST(self) -> None:
                started = time.perf_counter()
                path = urlparse(self.path).path
                if path != "/v1/chat/completions":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                if not self._authorized():
                    server_ref.metrics.record_mismatch(
                        latency_ms=(time.perf_counter() - started) * 1000, status_code=401
                    )
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_api_key"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body_bytes = self.rfile.read(length)
                self._record(body_bytes)
                try:
                    body = json.loads(body_bytes.decode("utf-8"))
                except json.JSONDecodeError:
                    server_ref.metrics.record_mismatch(
                        latency_ms=(time.perf_counter() - started) * 1000, status_code=400
                    )
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return
                snapshot = server_ref._snapshot_from_body(body)
                streaming = bool(body.get("stream", False))
                try:
                    fixture = match_fixture(
                        snapshot,
                        server_ref._fixtures,
                        strict=True,
                        usage_counts=server_ref._usage_counts,
                    )
                except (NoFixtureMatch, AmbiguousFixtureMatch, FixtureReuseError) as exc:
                    latency_ms = (time.perf_counter() - started) * 1000
                    server_ref.metrics.record_mismatch(latency_ms=latency_ms, status_code=400)
                    diagnostic = format_mismatch(
                        exc, metrics=server_ref.metrics, latency_ms=latency_ms
                    )
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "fixture_mismatch", "diagnostic": diagnostic},
                    )
                    return

                profile = apply_profile(fixture.profile)
                if profile is not None:
                    if profile.timeout_hold_ms:
                        time.sleep(profile.timeout_hold_ms / 1000.0)
                    if profile.raw_body is not None:
                        server_ref.metrics.record_match(
                            fixture.name,
                            latency_ms=(time.perf_counter() - started) * 1000,
                            status_code=profile.status_code,
                        )
                        self._send_bytes(profile.status_code, profile.raw_body, profile.headers)
                        return
                    if profile.status_code >= 400:
                        server_ref.metrics.record_match(
                            fixture.name,
                            latency_ms=(time.perf_counter() - started) * 1000,
                            status_code=profile.status_code,
                        )
                        self._send_json(profile.status_code, profile.body or {}, profile.headers)
                        return

                write_record(request=snapshot, fixture=fixture)

                if streaming or (profile and profile.disconnect_after_chunk is not None):
                    chunks = _sse_chunks(fixture)
                    disconnect_at = profile.disconnect_after_chunk if profile else None
                    body_out = b""
                    for index, chunk in enumerate(chunks):
                        if disconnect_at is not None and index >= disconnect_at:
                            server_ref.metrics.record_disconnect()
                            break
                        body_out += chunk.encode("utf-8")
                    headers = {"Content-Type": "text/event-stream", **fixture.response.headers}
                    server_ref.metrics.record_match(
                        fixture.name,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        status_code=200,
                    )
                    self._send_bytes(200, body_out, headers)
                    return

                response_body = _chat_completion_from_fixture(fixture)
                server_ref.metrics.record_match(
                    fixture.name,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status_code=fixture.response.status_code,
                )
                self._send_json(
                    fixture.response.status_code, response_body, fixture.response.headers
                )

        self._httpd = ThreadingHTTPServer((self._host, 0), Handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._httpd = None
        self._thread = None

    @staticmethod
    def _snapshot_from_body(body: dict[str, Any]) -> dict[str, Any]:
        model = str(body.get("model", "dummy"))
        provider = "default"
        if "/" in model:
            provider, model = model.split("/", 1)
        return {
            "provider": provider,
            "model": model,
            "mode": body.get("mode"),
            "streaming": bool(body.get("stream", False)),
            "turn_index": int(body.get("turn_index", 0)),
            "has_tool_results": body.get("has_tool_results"),
            "test_context_id": body.get("test_context_id"),
            "tool_call_id": body.get("tool_call_id"),
            "tool_result_content": body.get("tool_result_content"),
            "body": body,
        }

    @classmethod
    def load_fixtures_from_paths(cls, paths: list[str]) -> list[FixtureSpec]:
        return [load_fixture_file(Path(raw)) for raw in paths]
