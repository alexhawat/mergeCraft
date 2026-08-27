#!/usr/bin/env python3
"""Guard: ``action.yml`` slim image digest must match GHCR for the workflow Action SHA.

The published Docker action must pull a digest-pinned ``ghcr.io/alexhawat/mergecraft``
image instead of rebuilding from ``Dockerfile`` on every run (#526). When CI/CD
has published a slim image for the self-review workflow's Action SHA pin, this
script compares that registry digest to ``action.yml``'s ``runs.image`` pin.

When no GHCR tag exists yet for the pinned Action SHA (chicken-and-egg after a
pin bump before the next ``build-images`` push), the registry half is skipped
with a notice — same fail-open spirit as ``check_action_pin_freshness`` offline
skips.

Module: scripts.check_action_image_digest
Depends: re, sys, urllib.error, urllib.request, pathlib, yaml

Exports:
    main — CLI entry; compares action.yml digest vs published GHCR slim image.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ACTION_YML = REPO / "action.yml"
WORKFLOW_DIR = REPO / ".github" / "workflows"
SELF_REVIEW_WORKFLOW = WORKFLOW_DIR / "mergecraft.yml"

SLIM_IMAGE_REPO = "alexhawat/mergecraft"
SLIM_IMAGE = f"ghcr.io/{SLIM_IMAGE_REPO}"
GHCR_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)

_ACTION_PIN_RE = re.compile(r"uses:\s*alexhawat/mergeCraft@(?P<sha>[0-9a-f]{40})")
_DIGEST_IMAGE_RE = re.compile(
    rf"^docker://{re.escape(SLIM_IMAGE)}@sha256:([a-f0-9]{{64}})$"
)


def _pins_in(text: str) -> list[str]:
    return [match.group("sha") for match in _ACTION_PIN_RE.finditer(text)]


def _read_action_image() -> str | None:
    if not ACTION_YML.is_file():
        return None
    payload = ACTION_YML.read_text(encoding="utf-8")
    data = __import__("yaml").safe_load(payload)
    runs = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(runs, dict):
        return None
    image = runs.get("image")
    return image if isinstance(image, str) else None


def _ghcr_pull_token() -> str | None:
    """Return a registry pull token (anonymous for public packages, or via env)."""
    auth_header: str | None = None
    gh_token = __import__("os").environ.get("GITHUB_TOKEN") or __import__("os").environ.get(
        "GH_TOKEN"
    )
    if gh_token:
        auth_header = f"Bearer {gh_token}"
    url = (
        "https://ghcr.io/token?service=ghcr.io"
        f"&scope=repository:{SLIM_IMAGE_REPO}:pull"
    )
    try:
        request = urllib.request.Request(url)
        if auth_header:
            request.add_header("Authorization", auth_header)
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    token = payload.get("token")
    return token if isinstance(token, str) and token else None


def _ghcr_digest_for_tag(tag: str) -> str | None:
    """Return ``sha256:…`` digest for the slim image tag, or ``None`` when absent."""
    token = _ghcr_pull_token()
    if token is None:
        return None
    url = f"https://ghcr.io/v2/{SLIM_IMAGE_REPO}/manifests/{tag}"
    request = urllib.request.Request(url, method="HEAD")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", GHCR_MANIFEST_ACCEPT)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            digest = response.headers.get("docker-content-digest")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        return None
    except OSError:
        return None
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        return None
    return digest


def _self_review_action_sha() -> str | None:
    if not SELF_REVIEW_WORKFLOW.is_file():
        return None
    pins = _pins_in(SELF_REVIEW_WORKFLOW.read_text(encoding="utf-8"))
    if not pins:
        return None
    distinct = set(pins)
    if len(distinct) != 1:
        return None
    return pins[0]


def main() -> int:
    """Validate action.yml image contract and optional GHCR parity."""
    image = _read_action_image()
    if image is None:
        print("action-image-digest-check: action.yml missing runs.image", file=sys.stderr)
        return 1

    if image == "Dockerfile" or image.endswith("/Dockerfile"):
        print(
            "action-image-digest-check FAILED: action.yml still builds from Dockerfile — "
            "pin docker://ghcr.io/alexhawat/mergecraft@sha256:<digest> (#526)",
            file=sys.stderr,
        )
        return 1

    match = _DIGEST_IMAGE_RE.match(image)
    if match is None:
        print(
            f"action-image-digest-check FAILED: runs.image must be digest-pinned slim image "
            f"docker://{SLIM_IMAGE}@sha256:<64-hex> — got {image!r}",
            file=sys.stderr,
        )
        return 1

    pinned = f"sha256:{match.group(1)}"
    if "analyzers" in image:
        print(
            "action-image-digest-check FAILED: Action must use the slim image, not analyzers",
            file=sys.stderr,
        )
        return 1

    action_sha = _self_review_action_sha()
    if action_sha is None:
        print(
            "action-image-digest-check OK: action.yml digest-pinned "
            f"({pinned[:19]}…) — no self-review Action SHA to compare"
        )
        return 0

    published = _ghcr_digest_for_tag(action_sha)
    if published is None:
        print(
            f"action-image-digest-check: skipped GHCR parity — no published slim image for "
            f"Action SHA {action_sha[:12]} (tag missing or registry unreachable). "
            f"action.yml pins {pinned[:19]}…; bump after the next ci-cd build-images push."
        )
        return 0

    if published != pinned:
        print("action-image-digest-check FAILED:", file=sys.stderr)
        print(
            f"  action.yml pins {pinned}",
            file=sys.stderr,
        )
        print(
            f"  GHCR {SLIM_IMAGE}:{action_sha[:12]} publishes {published}",
            file=sys.stderr,
        )
        print(
            "  Update action.yml runs.image to the published slim digest for this Action SHA.",
            file=sys.stderr,
        )
        return 1

    print(
        f"action-image-digest-check OK: action.yml matches GHCR slim digest for "
        f"Action SHA {action_sha[:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
