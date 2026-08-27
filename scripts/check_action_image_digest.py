#!/usr/bin/env python3
"""Guard: ``action.yml`` slim image digest must match GHCR for the workflow Action SHA.

The published Docker action must pull a digest-pinned ``ghcr.io/alexhawat/mergecraft``
image instead of rebuilding from ``Dockerfile`` on every run (#526). When CI/CD
has published a slim image for the self-review workflow's Action SHA pin, this
script compares that registry digest to ``action.yml``'s ``runs.image`` pin and
verifies the image was built with ``--extra tracing`` (#531).

Registry outcomes are handled separately:
- reachable + tag present → digest must match ``action.yml``
- reachable + tag missing → **fail** (chicken-and-egg blocks a stale digest)
- unreachable → skip with a notice (offline / local ``make lint``)

Module: scripts.check_action_image_digest
Depends: json, re, sys, urllib.error, urllib.request, pathlib, yaml

Exports:
    main — CLI entry; compares action.yml digest vs published GHCR slim image.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ACTION_YML = REPO / "action.yml"
SELF_REVIEW_WORKFLOW = REPO / ".github" / "workflows" / "mergecraft.yml"

SLIM_IMAGE_REPO = "alexhawat/mergecraft"
SLIM_IMAGE = f"ghcr.io/{SLIM_IMAGE_REPO}"
GHCR_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)
OCI_REVISION_LABEL = "org.opencontainers.image.revision"

_ACTION_PIN_RE = re.compile(r"uses:\s*alexhawat/mergeCraft@(?P<sha>[0-9a-f]{40})")
_DIGEST_IMAGE_RE = re.compile(rf"^docker://{re.escape(SLIM_IMAGE)}@sha256:([a-f0-9]{{64}})$")


class TagLookupStatus(Enum):
    FOUND = "found"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True)
class TagLookupResult:
    status: TagLookupStatus
    digest: str | None = None


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
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{SLIM_IMAGE_REPO}:pull"
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


def _registry_reachable() -> bool:
    return _ghcr_pull_token() is not None


def _ghcr_digest_for_tag(tag: str) -> TagLookupResult:
    """Resolve the slim image digest for ``tag``, distinguishing missing vs errors."""
    token = _ghcr_pull_token()
    if token is None:
        return TagLookupResult(status=TagLookupStatus.ERROR)
    url = f"https://ghcr.io/v2/{SLIM_IMAGE_REPO}/manifests/{tag}"
    request = urllib.request.Request(url, method="HEAD")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", GHCR_MANIFEST_ACCEPT)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            digest = response.headers.get("docker-content-digest")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return TagLookupResult(status=TagLookupStatus.MISSING)
        return TagLookupResult(status=TagLookupStatus.ERROR)
    except OSError:
        return TagLookupResult(status=TagLookupStatus.ERROR)
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        return TagLookupResult(status=TagLookupStatus.ERROR)
    return TagLookupResult(status=TagLookupStatus.FOUND, digest=digest)


def _fetch_oci_config(index_digest: str) -> dict[str, Any] | None:
    """Return the OCI image config JSON for a manifest index digest."""
    token = _ghcr_pull_token()
    if token is None:
        return None
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{SLIM_IMAGE_REPO}/manifests/{index_digest}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": GHCR_MANIFEST_ACCEPT,
        },
    )
    try:
        index = json.loads(urllib.request.urlopen(request, timeout=30).read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or not manifests:
        return None
    platform = manifests[0]
    if not isinstance(platform, dict):
        return None
    manifest_digest = platform.get("digest")
    if not isinstance(manifest_digest, str):
        return None
    request_manifest = urllib.request.Request(
        f"https://ghcr.io/v2/{SLIM_IMAGE_REPO}/manifests/{manifest_digest}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": GHCR_MANIFEST_ACCEPT,
        },
    )
    try:
        manifest = json.loads(
            urllib.request.urlopen(request_manifest, timeout=30).read().decode("utf-8")
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    config = manifest.get("config")
    if not isinstance(config, dict):
        return None
    config_digest = config.get("digest")
    if not isinstance(config_digest, str):
        return None
    request_config = urllib.request.Request(
        f"https://ghcr.io/v2/{SLIM_IMAGE_REPO}/blobs/{config_digest}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        payload = json.loads(
            urllib.request.urlopen(request_config, timeout=30).read().decode("utf-8")
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _image_has_tracing_extra(config: dict[str, Any]) -> bool:
    """Return whether the slim image ``uv sync`` layer includes ``--extra tracing``."""
    history = config.get("history")
    if not isinstance(history, list):
        return False
    for entry in history:
        if not isinstance(entry, dict):
            continue
        created_by = entry.get("created_by")
        if isinstance(created_by, str) and "uv sync" in created_by:
            return "--extra tracing" in created_by
    return False


def _revision_from_config(config: dict[str, Any]) -> str | None:
    labels = config.get("config", {}).get("Labels")
    if not isinstance(labels, dict):
        return None
    revision = labels.get(OCI_REVISION_LABEL)
    return revision if isinstance(revision, str) and revision else None


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
    """Validate action.yml image contract and GHCR parity."""
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

    if not _registry_reachable():
        print(
            "action-image-digest-check: skipped GHCR parity — registry unreachable "
            f"(action.yml pins {pinned[:19]}…)"
        )
        return 0

    pinned_config = _fetch_oci_config(pinned)
    if pinned_config is None:
        print(
            "action-image-digest-check FAILED: could not read OCI config for pinned digest "
            f"{pinned}",
            file=sys.stderr,
        )
        return 1

    if not _image_has_tracing_extra(pinned_config):
        print(
            "action-image-digest-check FAILED: pinned slim image was built without "
            "`uv sync --extra tracing` — Logfire/OTEL sinks degrade to NullSink (#531). "
            f"Do not pin pre-#531 digests such as {pinned[:19]}…",
            file=sys.stderr,
        )
        return 1

    action_sha = _self_review_action_sha()
    if action_sha is None:
        print(
            "action-image-digest-check OK: digest-pinned slim image includes tracing extra "
            f"({pinned[:19]}…) — no self-review Action SHA to compare"
        )
        return 0

    pinned_revision = _revision_from_config(pinned_config)
    if pinned_revision is not None and pinned_revision != action_sha:
        print("action-image-digest-check FAILED:", file=sys.stderr)
        print(
            f"  action.yml pins {pinned} ({OCI_REVISION_LABEL}={pinned_revision})",
            file=sys.stderr,
        )
        print(
            f"  mergecraft.yml Action SHA is {action_sha}",
            file=sys.stderr,
        )
        return 1

    lookup = _ghcr_digest_for_tag(action_sha)
    if lookup.status is TagLookupStatus.ERROR:
        print(
            "action-image-digest-check: skipped GHCR parity — registry error while "
            f"resolving {SLIM_IMAGE}:{action_sha[:12]} (action.yml pins {pinned[:19]}…)"
        )
        return 0

    if lookup.status is TagLookupStatus.MISSING:
        print("action-image-digest-check FAILED:", file=sys.stderr)
        print(
            f"  no published slim image for Action SHA {action_sha} "
            f"(expected tag {SLIM_IMAGE}:{action_sha})",
            file=sys.stderr,
        )
        print(
            f"  action.yml pins {pinned} — run ci-cd build-images on pre-0.0.1, "
            "then bump runs.image to that digest",
            file=sys.stderr,
        )
        return 1

    published = lookup.digest
    assert published is not None
    if published != pinned:
        print("action-image-digest-check FAILED:", file=sys.stderr)
        print(f"  action.yml pins {pinned}", file=sys.stderr)
        print(f"  GHCR {SLIM_IMAGE}:{action_sha[:12]} publishes {published}", file=sys.stderr)
        print(
            "  Update action.yml runs.image to the published slim digest for this Action SHA.",
            file=sys.stderr,
        )
        return 1

    print(
        f"action-image-digest-check OK: action.yml matches GHCR slim digest for "
        f"Action SHA {action_sha[:12]} (tracing extra present)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
