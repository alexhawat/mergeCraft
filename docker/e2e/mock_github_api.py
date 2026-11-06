#!/usr/bin/env python3
"""Local GitHub mock for real Action review protocol and publication checks."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse


class _Handler(BaseHTTPRequestHandler):
    check_runs_dir: Path
    fixture: ClassVar[dict[str, Any]] = {}
    reviews: ClassVar[dict[str, dict[str, Any]]] = {}
    lock = threading.Lock()
    sequence = 0

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"[mock-github] {fmt % args}\n")

    def _send(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}"
        )
        return body

    def _record(self, body: dict[str, Any]) -> int:
        with self.lock:
            type(self).sequence += 1
            number = self.sequence
            directory = self.check_runs_dir / "requests"
            directory.mkdir(parents=True, exist_ok=True)
            record = {"method": self.command, "path": urlparse(self.path).path, "body": body}
            (directory / f"{number:04d}.json").write_text(json.dumps(record))
            if self.path.endswith("/check-runs"):
                (self.check_runs_dir / f"{number:04d}.json").write_text(json.dumps(record))
        return number

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        pull = self.fixture.get("pull_request", {})
        repository = self.fixture.get("repository", {})
        if path in self.reviews:
            self._send(200, self.reviews[path])
        elif path.endswith("/contents/.mergecraft/config.yaml"):
            config = Path(__file__).parent / "fixtures/repo/.mergecraft/config.yaml"
            self._send(
                200,
                {"encoding": "base64", "content": base64.b64encode(config.read_bytes()).decode()},
            )
        elif path.endswith("/files"):
            self._send(200, self.fixture.get("_e2e_files", []))
        elif path == "/app":
            self._send(200, {"id": 7, "slug": "mergecraft-e2e"})
        elif path == "/user":
            self._send(200, {"login": "mergecraft-e2e[bot]", "type": "Bot"})
        elif re.fullmatch(r"/repos/[^/]+/[^/]+", path):
            self._send(200, {"id": 1, **repository})
        elif re.fullmatch(r"/repos/[^/]+/[^/]+/pulls/\d+", path):
            self._send(200, {"html_url": "https://example.test/pull/42", **pull})
        elif path.endswith("/reviews"):
            self._send(
                200, [review for key, review in self.reviews.items() if key.startswith(path + "/")]
            )
        elif path.endswith(("/comments", "/events", "/labels")):
            self._send(200, [])
        elif path.endswith("/check-runs"):
            self._send(200, {"total_count": 0, "check_runs": []})
        elif path.endswith("/check-suites"):
            self._send(200, {"total_count": 0, "check_suites": []})
        elif path.endswith("/actions/runs"):
            self._send(200, {"total_count": 0, "workflow_runs": []})
        else:
            self._send(404, {"message": f"Not Found: {path}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._body()
        if path == "/_e2e/fixture":
            type(self).fixture = body
            type(self).sequence = 0
            type(self).reviews = {}
            for directory in (self.check_runs_dir, self.check_runs_dir / "requests"):
                for record in directory.glob("*.json"):
                    record.unlink()
            self._send(200, {"configured": True})
            return
        if path == "/graphql":
            self._send(
                200,
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "closingIssuesReferences": {
                                    "nodes": [],
                                    "pageInfo": {"hasNextPage": False},
                                },
                                "reviewThreads": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                            }
                        }
                    }
                },
            )
            return
        if re.fullmatch(
            r"/repos/[^/]+/[^/]+/(check-runs|pulls/\d+/reviews|issues/\d+/comments)", path
        ):
            number = self._record(body)
            response = {
                "id": number,
                "html_url": f"https://example.test/records/{number}",
                "user": {"login": "mergecraft-e2e[bot]", "type": "Bot"},
                "state": {
                    "APPROVE": "APPROVED",
                    "REQUEST_CHANGES": "CHANGES_REQUESTED",
                    "COMMENT": "COMMENTED",
                }.get(str(body.get("event")), "PENDING"),
                **body,
            }
            if path.endswith("/reviews"):
                self.reviews[f"{path}/{number}"] = response
            self._send(201, response)
            return
        self._send(404, {"message": f"Not Found: {path}"})

    def do_PUT(self) -> None:
        self._update()

    def do_PATCH(self) -> None:
        self._update()

    def _update(self) -> None:
        path = urlparse(self.path).path
        if not re.fullmatch(
            r"/repos/[^/]+/[^/]+/(pulls/\d+/reviews/\d+|issues/comments/\d+|check-runs/\d+)", path
        ):
            self._send(404, {"message": f"Not Found: {path}"})
            return
        body = self._body()
        self._record(body)
        response = {
            **self.reviews.get(path, {}),
            "id": int(path.rsplit("/", 1)[1]),
            "html_url": "https://example.test/review",
            **body,
        }
        if path in self.reviews:
            self.reviews[path] = response
        self._send(200, response)


def create_server(host: str, port: int, directory: Path) -> ThreadingHTTPServer:
    directory.mkdir(parents=True, exist_ok=True)
    handler = type(
        "FixtureHandler",
        (_Handler,),
        {"check_runs_dir": directory, "fixture": {}, "sequence": 0, "reviews": {}},
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check-runs-dir", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.check_runs_dir)
    if args.ready_file:
        args.ready_file.write_text(f"{args.host}:{server.server_port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
