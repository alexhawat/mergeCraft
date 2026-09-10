#!/usr/bin/env python3
"""Verify the manifest commit actually pinned by a consumer against signed image provenance.

Source validation is deliberately separate from deployed C → D → S verification.
Only strict verification produces a verified result; offline mode exits 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

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

_ENV_SHA_RE = re.compile(
    r"^\s*MERGECRAFT_ACTION_SHA:\s*[\"']?(?P<sha>[0-9a-f]{40})[\"']?\s*$",
    re.MULTILINE,
)
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


# Retry post-publication tag visibility before accepting canonical readback.
# Registry errors remain fatal; an unsigned existing tag is never overwritten.
_MISSING_RETRIES = int(os.environ.get("MERGECRAFT_GHCR_MISSING_RETRIES", "3"))
_MISSING_BACKOFF_SECONDS = float(os.environ.get("MERGECRAFT_GHCR_MISSING_BACKOFF", "3"))


def _ghcr_digest_for_tag(tag: str) -> TagLookupResult:
    """Resolve the slim image digest for ``tag``, retrying a not-yet-visible push.

    ``MISSING`` is retried because it is the one status that is routinely
    transient right after a push. ``ERROR`` is not: a registry fault or a bad
    token will not resolve itself inside a few seconds, and retrying it would
    only delay the required failure.
    """
    result = _ghcr_digest_for_tag_once(tag)
    attempts = 0
    while result.status is TagLookupStatus.MISSING and attempts < _MISSING_RETRIES:
        time.sleep(_MISSING_BACKOFF_SECONDS)
        attempts += 1
        result = _ghcr_digest_for_tag_once(tag)
    return result


def _ghcr_digest_for_tag_once(tag: str) -> TagLookupResult:
    """One HEAD against the registry, distinguishing missing from errors."""
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


def _fetch_oci_config_for_tag(tag: str) -> dict[str, Any] | None:
    """Read content-addressed registry objects and verify every returned byte hash."""
    token = _ghcr_pull_token()
    if token is None or not re.fullmatch(r"sha256:[0-9a-f]{64}", tag):
        return None

    def fetch(kind: str, digest: str) -> dict[str, Any]:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("registry descriptor is not a SHA256 digest")
        request = urllib.request.Request(
            f"https://ghcr.io/v2/{SLIM_IMAGE_REPO}/{kind}/{digest}",
            headers={"Authorization": f"Bearer {token}", "Accept": GHCR_MANIFEST_ACCEPT},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("registry object does not match its digest")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("registry object is not a mapping")
        return value

    try:
        root = fetch("manifests", tag)
        descriptors = root.get("manifests")
        if isinstance(descriptors, list):
            # BuildKit adds unknown/unknown attestation descriptors. Verify every
            # runnable platform, not whichever descriptor happens to be first.
            manifests = [
                fetch("manifests", item["digest"])
                for item in descriptors
                if item.get("platform", {}).get("os") != "unknown"
            ]
        else:
            manifests = [root]
        configs = [fetch("blobs", item["config"]["digest"]) for item in manifests]
        if not configs:
            return None
        revision = _revision_from_config(configs[0])
        if any(
            _revision_from_config(c) != revision
            or _image_has_tracing_extra(c) != _image_has_tracing_extra(configs[0])
            for c in configs
        ):
            return None
        return configs[0]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


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
    image_config = config.get("config")
    if not isinstance(image_config, dict):
        return None
    labels = image_config.get("Labels")
    if not isinstance(labels, dict):
        return None
    revision = labels.get(OCI_REVISION_LABEL)
    return revision if isinstance(revision, str) and revision else None


def _self_review_action_sha() -> str | None:
    if not SELF_REVIEW_WORKFLOW.is_file():
        return None
    text = SELF_REVIEW_WORKFLOW.read_text(encoding="utf-8")
    pins = set(_pins_in(text))
    if len(pins) != 1:
        return None
    pin = next(iter(pins))
    env_match = _ENV_SHA_RE.search(text)
    if env_match is not None and env_match.group("sha") != pin:
        return None
    return pin


class VerificationError(ValueError):
    """The deployment cannot be proven against the trusted release policy."""


@dataclass(frozen=True)
class VerifiedManifest:
    manifest_commit: str
    source_revision: str
    image_digest: str
    verified: bool = True


def _run(repo: Path, argv: list[str]) -> str:
    """Run a bounded verifier without shell interpolation or credential output."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    try:
        result = subprocess.run(
            argv, cwd=repo, env=env, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"verification tool unavailable: {argv[0]}") from exc
    if result.returncode:
        raise VerificationError(f"{argv[0]} verification failed (exit {result.returncode})")
    return result.stdout


def _git(repo: Path, *args: str) -> str:
    return _run(
        repo, ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args]
    )


def _commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise VerificationError("expected an immutable 40-hex Git commit")
    return value


def _action_at(repo: Path, commit: str) -> dict[str, Any]:
    data = yaml.safe_load(_git(repo, "show", f"{_commit(commit)}:action.yml"))
    if not isinstance(data, dict) or not isinstance(data.get("runs"), dict):
        raise VerificationError("pinned action.yml lacks a runs mapping")
    return data


def _digest_from_action(data: dict[str, Any]) -> str:
    image = data["runs"].get("image", "")
    match = _DIGEST_IMAGE_RE.fullmatch(image) if isinstance(image, str) else None
    if match is None:
        raise VerificationError("action must name the slim image by SHA256 digest")
    return "sha256:" + match.group(1)


_RELEASE_IDENTITY = (
    r"^https://github\.com/alexhawat/mergeCraft/\.github/workflows/ci-cd\.yml@"
    r"refs/(heads/(main|pre-0\.0\.1|release/[^ ]+)|tags/v[^ ]+)$"
)


def _attestation_policy(source: str) -> list[str]:
    """Return compatible gh policy flags; the identity regex includes workflow and ref."""
    return [
        "--repo",
        "alexhawat/mergeCraft",
        "--source-digest",
        _commit(source),
        "--signer-digest",
        source,
        "--cert-identity-regex",
        _RELEASE_IDENTITY,
        "--cert-oidc-issuer",
        "https://token.actions.githubusercontent.com",
        "--deny-self-hosted-runners",
    ]


def _verify_attestations(repo: Path, digest: str, source: str) -> None:
    """Cryptographically bind D to S and the approved GitHub-hosted release workflow."""
    image = f"{SLIM_IMAGE}@{digest}"
    common = _attestation_policy(source)
    _run(repo, ["gh", "attestation", "verify", f"oci://{image}", *common])
    _run(
        repo,
        [
            "gh",
            "attestation",
            "verify",
            f"oci://{image}",
            *common,
            "--predicate-type",
            "https://spdx.dev/Document",
        ],
    )
    _run(
        repo,
        [
            "cosign",
            "verify",
            "--certificate-identity-regexp",
            _RELEASE_IDENTITY,
            "--certificate-oidc-issuer",
            "https://token.actions.githubusercontent.com",
            image,
        ],
    )


def verify_image(
    repo: Path, digest: str, expected_source: str | None = None, *, require_tracing: bool = True
) -> str:
    """Return S only after digest-addressed content and external attestations verify."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise VerificationError("expected an immutable image digest")
    config = _fetch_oci_config_for_tag(digest)
    if config is None:
        raise VerificationError("registry content unavailable or invalid")
    source = _revision_from_config(config)
    if source is None:
        raise VerificationError("image lacks its source revision")
    _commit(source)
    if expected_source is not None and source != _commit(expected_source):
        raise VerificationError("image source differs from the requested source")
    if require_tracing and not _image_has_tracing_extra(config):
        raise VerificationError("image was built without the tracing extra")
    _verify_attestations(repo, digest, source)
    return source


def verify_manifest(repo: Path, manifest_commit: str) -> VerifiedManifest:
    """Verify C→D→S; C may differ from S only in the action's image field."""
    manifest_commit = _commit(manifest_commit)
    action = _action_at(repo, manifest_commit)
    digest = _digest_from_action(action)
    source = verify_image(repo, digest)
    changed = _git(repo, "diff", "--name-only", source, manifest_commit, "--").splitlines()
    if any(path != "action.yml" for path in changed):
        raise VerificationError(
            "manifest commit changes files beyond action.yml relative to image source"
        )
    source_action = _action_at(repo, source)
    action["runs"].pop("image", None)
    source_action["runs"].pop("image", None)
    if action != source_action:
        raise VerificationError("manifest commit changes Action behavior beyond runs.image")
    return VerifiedManifest(manifest_commit, source, digest)


def _workflow_pins(text: str, *, strict: bool = True) -> set[str]:
    """Parse literal Action references and exported pin markers, rejecting mutable refs."""
    pins: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key == "uses"
                    and isinstance(child, str)
                    and child.lower().startswith("alexhawat/mergecraft@")
                ):
                    reference = child.split("@", 1)[1]
                    pins.add(_commit(reference) if strict else reference)
                elif key == "MERGECRAFT_ACTION_SHA":
                    pins.add(_commit(str(child)) if strict else str(child))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(yaml.safe_load(text))
    return pins


def _digest_introducer(repo: Path, base: str, head: str, image: Any) -> str:
    """The commit in ``base..head`` that introduced *head*'s Action image.

    ``verify_manifest`` checks that a manifest commit differs from its image
    source in ``action.yml`` alone. Verifying *head* directly assumed head was
    that commit — false for any merge, which carries the digest plus everything
    merged alongside it. That rejected ``dac17243`` after #669 landed as a merge
    and failed the first ``pre-0.0.1`` forward-port outright (#684).

    Asking instead "did a parent already have this ``action.yml``?" is not a fix:
    a parent inside the candidate range proves nothing, since a PR can introduce
    a bad digest in one commit and inherit it in the next without either being
    verified.

    So find the commit that actually introduced the image and verify *that*. A
    forward-port resolves to the real manifest commit, which passes; a digest
    minted mid-PR resolves to the commit that minted it, which is checked on its
    own terms and fails if it changed anything beyond ``action.yml``.
    """
    if not image:
        return head
    try:
        head_action = _action_at(repo, head)
    except (VerificationError, KeyError, TypeError):
        return head
    revs = (
        _git(repo, "rev-list", "--reverse", f"{base}..{head}", "--", "action.yml") or ""
    ).split()
    for rev in revs:
        try:
            candidate = _action_at(repo, rev)
        except (VerificationError, KeyError, TypeError):
            continue
        if candidate["runs"].get("image") != image:
            continue
        # Substitute only when head's Action is byte-identical to the
        # introducer's. Matching on the image alone would let a later commit
        # inherit a legitimate digest while adding its own `entrypoint:`, and
        # that change would never be verified.
        return rev if candidate == head_action else head
    return head


def verify_candidate(repo: Path, base: str, head: str) -> dict[str, Any]:
    """Verify deployment boundary changes without requiring source S to be published."""
    base, head = _commit(base), _commit(head)
    if base == "0" * 40:
        base = _commit(_git(repo, "rev-parse", f"{head}^").strip())
    changed = set(_git(repo, "diff", "--name-only", base, head, "--").splitlines())
    manifests: set[str] = set()
    if "action.yml" in changed:
        before, after = _action_at(repo, base), _action_at(repo, head)
        if before["runs"].get("image") != after["runs"].get("image"):
            manifests.add(_digest_introducer(repo, base, head, after["runs"].get("image")))
    base_paths = set(
        _git(repo, "ls-tree", "-r", "--name-only", base, "--", ".github/workflows").splitlines()
    )
    head_paths = set(
        _git(repo, "ls-tree", "-r", "--name-only", head, "--", ".github/workflows").splitlines()
    )
    for path in sorted(changed & (base_paths | head_paths)):
        if not path.endswith((".yml", ".yaml")):
            continue
        old = (
            _workflow_pins(_git(repo, "show", f"{base}:{path}"), strict=False)
            if path in base_paths
            else set()
        )
        new = _workflow_pins(_git(repo, "show", f"{head}:{path}")) if path in head_paths else set()
        if old != new:
            manifests.update(new)
    records = [verify_manifest(repo, commit).__dict__ for commit in sorted(manifests)]
    return {
        "state": "deployment-candidates-verified" if records else "source-only-change",
        "base_commit": base,
        "head_commit": head,
        "manifests": records,
    }


def main(argv: list[str] | None = None) -> int:
    """Check deployed pins strictly, or explicitly report unverified source structure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-commit")
    parser.add_argument("--candidate", action="store_true")
    parser.add_argument("--structure-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv or [])
    try:
        if args.candidate:
            result = verify_candidate(
                REPO, os.environ.get("CANDIDATE_BASE", ""), os.environ.get("CANDIDATE_HEAD", "")
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.structure_only:
            data = yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))
            _digest_from_action(data)
            print("UNVERIFIED: source Action image syntax valid; deployed provenance not checked")
            return 0
        commit = args.manifest_commit or _self_review_action_sha()
        if commit is None:
            raise VerificationError("self-review Action pin missing or ambiguous")
        if args.offline:
            _digest_from_action(_action_at(REPO, commit))
            print("UNVERIFIED: pinned manifest syntax valid; offline verification requested")
            return 2
        result = verify_manifest(REPO, commit)
        print(json.dumps(result.__dict__, sort_keys=True))
        return 0
    except (VerificationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"action-image-digest-check FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
