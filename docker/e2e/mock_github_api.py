#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Minimal GitHub REST mock for the Action-image E2E gate (W11 / D6).

Serves the endpoints ``mergecraft gha`` hits during a fixture run:

- ``GET /repos/{owner}/{repo}``
- ``GET /repos/{owner}/{repo}/pulls/{n}``
- ``POST /repos/{owner}/{repo}/check-runs`` (recorded for assertions)

No live network; bind to ``127.0.0.1`` and point ``GITHUB_API_URL`` at it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_RE = re.compile(r"^/repos/([^/]+)/([^/]+)$")
_PULL_RE = re.compile(r"^/repos/([^/]+)/([^/]+)/pulls/(\d+)$")
_CHECK_RE = re.compile(r"^/repos/([^/]+)/([^/]+)/check-runs$")

_HEAD_SHA_BY_PR: dict[int, str] = {
    42: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    43: "cccccccccccccccccccccccccccccccccccccccc",
}


class _Handler(BaseHTTPRequestHandler):
    check_runs_dir: Path

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"[mock-github] {self.address_string()} - {fmt % args}\n")

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        repo_match = _REPO_RE.match(path)
        if repo_match:
            owner, name = repo_match.group(1), repo_match.group(2)
            self._send_json(
                200,
                {
                    "id": 1,
                    "name": name,
                    "full_name": f"{owner}/{name}",
                    "private": False,
                    "owner": {"login": owner},
                    "default_branch": "main",
                },
            )
            return
        pull_match = _PULL_RE.match(path)
        if pull_match:
            owner, name, number_s = pull_match.groups()
            number = int(number_s)
            sha = _HEAD_SHA_BY_PR.get(number, "d" * 40)
            self._send_json(
                200,
                {
                    "number": number,
                    "state": "open",
                    "title": f"E2E fixture PR #{number}",
                    "head": {
                        "ref": "feature/e2e-fixture",
                        "sha": sha,
                        "repo": {"full_name": f"{owner}/{name}"},
                    },
                    "base": {"ref": "main", "sha": "b" * 40},
                },
            )
            return
        self._send_json(404, {"message": f"Not Found: {path}"})

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        check_match = _CHECK_RE.match(path)
        if check_match:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {"_raw": raw.decode("utf-8", errors="replace")}
            owner, name = check_match.group(1), check_match.group(2)
            out_dir = self.check_runs_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = len(list(out_dir.glob("*.json")))
            check_name = str(body.get("name") or "unnamed").replace("/", "_")
            dest = out_dir / f"{stamp:02d}-{check_name}.json"
            dest.write_text(
                json.dumps(
                    {"owner": owner, "repo": name, "body": body},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._send_json(201, {"id": stamp + 1, "name": body.get("name"), "html_url": ""})
            return
        self._send_json(404, {"message": f"Not Found: {path}"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--check-runs-dir",
        type=Path,
        required=True,
        help="Directory where POSTed check-run bodies are recorded",
    )
    parser.add_argument(
        "--ready-file",
        type=Path,
        default=None,
        help="Optional path written once the server is listening",
    )
    args = parser.parse_args()
    args.check_runs_dir.mkdir(parents=True, exist_ok=True)
    _Handler.check_runs_dir = args.check_runs_dir
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    if args.ready_file is not None:
        args.ready_file.write_text(f"{args.host}:{args.port}\n", encoding="utf-8")
    sys.stderr.write(f"[mock-github] listening on http://{args.host}:{args.port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
