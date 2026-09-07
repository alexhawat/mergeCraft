#!/usr/bin/env python3
"""Prepare the two reviewed commits C (manifest) then P (consumer pin).

This tool never commits, pushes, creates PRs, or claims CI ran. Both phases
require signed image verification; the pin phase requires C already merged.
Exports: prepare_manifest, prepare_pin, resolve_images, main.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from check_action_image_digest import (
    REPO,
    TagLookupStatus,
    VerificationError,
    _commit,
    _ghcr_digest_for_tag,
    _git,
    verify_image,
    verify_manifest,
)

_IMAGE_LINE = re.compile(
    r"(?m)^([ \t]*image:[ \t]*[\"']?)docker://ghcr\.io/alexhawat/mergecraft@sha256:[0-9a-f]{64}([\"']?[ \t]*(?:#.*)?)$"
)

_PIN = re.compile(r"(uses:\s*alexhawat/mergeCraft@)[0-9a-f]{40}")
_ENV_PIN = re.compile(r'(?m)^(\s*MERGECRAFT_ACTION_SHA:\s*["\']?)[0-9a-f]{40}')


def _clean(repo: Path) -> str:
    if _git(repo, "status", "--porcelain").strip():
        raise VerificationError("prepare release changes in a clean isolated worktree")
    return _commit(_git(repo, "rev-parse", "HEAD").strip())


def prepare_manifest(repo: Path, source: str, digest: str) -> dict[str, str]:
    """Change only action.yml at S; the caller reviews and merges it as C."""
    source = _commit(source)
    head = _clean(repo)
    verify_image(repo, digest, source)
    if head != source:
        # An already merged manifest is a safe idempotent no-op, not a rebuild.
        result = verify_manifest(repo, head)
        if result.source_revision != source or result.image_digest != digest:
            raise VerificationError("HEAD is not the built source or its verified manifest")
        return {
            "state": "manifest-already-present",
            "manifest_commit": head,
            "source_revision": source,
            "image_digest": digest,
        }
    path = repo / "action.yml"
    content, count = _IMAGE_LINE.subn(
        lambda match: f"{match[1]}docker://ghcr.io/alexhawat/mergecraft@{digest}{match[2]}",
        path.read_text(),
    )
    if count != 1:
        raise VerificationError("expected exactly one digest image line")
    path.write_text(content)
    return {"state": "manifest-change-prepared", "source_revision": source, "image_digest": digest}


def prepare_pin(repo: Path, manifest: str, base_branch: str = "pre-0.0.1") -> dict[str, str]:
    """Pin an already merged C; never point consumers at S just because it built D."""
    head = _clean(repo)
    manifest = _commit(manifest)
    if base_branch not in ("main", "pre-0.0.1"):
        raise VerificationError("consumer pins target main or pre-0.0.1 only")
    _git(repo, "merge-base", "--is-ancestor", manifest, f"origin/{base_branch}")
    _git(repo, "merge-base", "--is-ancestor", manifest, head)
    result = verify_manifest(repo, manifest)
    changes: list[tuple[Path, str]] = []
    consumer_pins = 0
    for name in ("mergecraft.yml", "mergecraft-approve.yml"):
        path = repo / ".github" / "workflows" / name
        if not path.is_file():
            continue
        content = path.read_text()
        consumer_pins += len(_PIN.findall(content))
        replaced = _ENV_PIN.sub(
            lambda match: match[1] + manifest, _PIN.sub(lambda match: match[1] + manifest, content)
        )
        if replaced != content:
            changes.append((path, replaced))
    if not consumer_pins:
        raise VerificationError("no self-review consumer Action references found")
    if not changes:
        return {
            "state": "pin-already-present",
            "manifest_commit": manifest,
            "source_revision": result.source_revision,
            "image_digest": result.image_digest,
        }
    for path, content in changes:
        path.write_text(content)
    return {
        "state": "pin-change-prepared",
        "manifest_commit": manifest,
        "source_revision": result.source_revision,
        "image_digest": result.image_digest,
    }


def resolve_images(repo: Path, source: str) -> dict[str, str]:
    """Reuse only verified SHA tags; registry errors/unsigned collisions fail closed."""
    source = _commit(source)
    outputs: dict[str, str] = {}
    for kind, tag in (("slim", source), ("analyzers", f"analyzers-{source}")):
        lookup = _ghcr_digest_for_tag(tag)
        if lookup.status is TagLookupStatus.ERROR:
            raise VerificationError("registry unavailable: cannot determine immutable tag state")
        if lookup.status is TagLookupStatus.MISSING:
            outputs[f"{kind}_digest"] = ""
            continue
        if lookup.digest is None:
            raise VerificationError("registry returned an empty image digest")
        verify_image(repo, lookup.digest, source, require_tracing=kind == "slim")
        outputs[f"{kind}_digest"] = lookup.digest
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("manifest", "pin", "resolve-images", "verify-images"))
    parser.add_argument("--source", default=os.environ.get("SOURCE_REVISION"))
    parser.add_argument("--digest", default=os.environ.get("IMAGE_DIGEST"))
    parser.add_argument("--manifest", default=os.environ.get("MANIFEST_COMMIT"))
    parser.add_argument("--base-branch", default=os.environ.get("RELEASE_BASE_BRANCH", "pre-0.0.1"))
    args = parser.parse_args(argv)
    try:
        if args.phase == "manifest":
            result = prepare_manifest(REPO, args.source or "", args.digest or "")
        elif args.phase == "pin":
            result = prepare_pin(REPO, args.manifest or "", args.base_branch)
        elif args.phase == "resolve-images":
            result = resolve_images(REPO, args.source or "")
            if output := os.environ.get("GITHUB_OUTPUT"):
                with Path(output).open("a") as stream:
                    stream.writelines(f"{key}={value}\n" for key, value in result.items())
        else:
            source = _commit(args.source or "")
            for kind in ("slim", "analyzers"):
                verify_image(
                    REPO,
                    os.environ.get(f"{kind.upper()}_DIGEST", ""),
                    source,
                    require_tracing=kind == "slim",
                )
            result = {"state": "images-verified", "source_revision": source}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (VerificationError, OSError, ValueError) as exc:
        print(f"action-pin preparation FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
